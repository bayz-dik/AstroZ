"""Hermes orchestrator: plan -> workers (parallel) -> discussion -> test -> review.

Every stage emits hub events so the web UI shows live what Hermes and each
worker are doing. Worker output is streamed line by line, not buffered.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from typing import Any

import adapters
import config
import hub
import project
from gateway import Gateway

TASKS: dict[str, dict] = {}
TASKS_FILE = config.RUNTIME / "tasks.json"
_TASK_FIELDS = (
    "id", "prompt", "status", "size", "workers", "model", "plan", "results",
    "test", "review", "summary", "commit", "created", "finished",
)


def _persist_tasks() -> None:
    """Keep task history across restarts (the UI and plugin both read it)."""
    try:
        items = sorted(TASKS.values(), key=lambda t: t.get("created", 0), reverse=True)[:60]
        slim = [{k: t.get(k) for k in _TASK_FIELDS if k in t} for t in items]
        TASKS_FILE.write_text(json.dumps(slim, ensure_ascii=False, default=str))
    except Exception:
        pass


def load_tasks() -> int:
    if not TASKS_FILE.exists():
        return 0
    try:
        items = json.loads(TASKS_FILE.read_text())
    except Exception:
        return 0
    for t in items:
        if isinstance(t, dict) and t.get("id"):
            # A task that was mid-flight when the server stopped is not running
            # any more: report it as interrupted instead of a permanent "running".
            if t.get("status") == "running":
                t["status"] = "interrupted"
            TASKS[t["id"]] = t
    return len(TASKS)
_TASK_LOCK = threading.Lock()


def get_task(tid: str) -> dict | None:
    return TASKS.get(tid)


def list_tasks(limit: int = 50) -> list[dict]:
    items = sorted(TASKS.values(), key=lambda t: t["created"], reverse=True)
    return [
        {
            "id": t["id"],
            "prompt": t["prompt"],
            "status": t["status"],
            "size": t.get("size"),
            "workflow": t.get("workflow"),
            "created": t["created"],
            "finished": t.get("finished"),
            "model": t.get("model"),
            "workers": t.get("workers", []),
            "summary": (t.get("summary") or "")[:2000],
        }
        for t in items[:limit]
    ]


def _is_retryable(text: str) -> bool:
    """True for transient upstream conditions that a retry can actually fix."""
    if not text:
        return True
    low = text.lower()
    for token in ("429", "503", "502", "all providers busy", "rate limit", "overloaded",
                  "timeout", "timed out", "connection reset", "temporarily unavailable"):
        if token in low:
            return True
    return False


def model_chain(cfg: dict, primary: str) -> list[str]:
    """Ordered models to try for a task: the selected one, then the fallbacks.

    A single free upstream provider saturates easily, so a task that dies on a
    429 is a routing problem, not a work problem. Fallbacks come from
    ``gateway.fallback_models`` and, when empty, from the models that answered
    the last health probe.
    """
    gw = cfg["gateway"]
    chain = [primary] if primary else []
    for m in gw.get("fallback_models") or []:
        if m and m not in chain:
            chain.append(m)
    if gw.get("auto_fallback", True):
        for m in gw.get("healthy") or []:
            if m and m not in chain:
                chain.append(m)
    return chain[:5]


def _pick_workers(cfg: dict, want: int) -> list[str]:
    enabled = [k for k, v in cfg["workers"].items() if v.get("enabled")]
    installed = [k for k in enabled if adapters.ADAPTERS[k].path or adapters.ADAPTERS[k].probe().get("installed")]
    order = [k for k in (cfg["workflow"].get("worker_order") or []) if k in adapters.ADAPTERS]
    if not order:
        order = list(adapters.ADAPTERS)
    installed = [k for k in order if k in installed]
    return installed[:want] if installed else enabled[:want]


def _worker_cost(cfg: dict, worker: str) -> float:
    """Typical cost of one run, in the config's own unit (USD per request)."""
    try:
        return float((cfg["workflow"].get("worker_cost") or {}).get(worker, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _pick_cheapest(cfg: dict, want: int = 1, exclude: set[str] | None = None) -> list[str]:
    """Installed workers, cheapest first, the escalation order for retries."""
    installed = [w for w in _pick_workers(cfg, 99) if w not in (exclude or set())]
    return sorted(installed, key=lambda w: (_worker_cost(cfg, w), _pick_workers(cfg, 99).index(w)))[:want]


def _worker_env(worker: str, model: str) -> dict:
    cfg = config.load()
    gw = {**cfg["gateway"], "model": model}
    return adapters.ADAPTERS[worker].env(gw, model)


def run_worker(worker: str, prompt: str, task_id: str, cwd: str, model: str, timeout: int = 900,
               retries: int = 3) -> dict:
    """Run one worker CLI, streaming its stdout/stderr into the hub.

    A worker that fails for a transient reason (gateway 429/503, provider busy,
    timeout) is retried, with a different worker if one is available, because
    the alternative is a task that dies for a reason the team can route around.
    """
    a = adapters.ADAPTERS[worker]
    if not a.path:
        a.probe()
    if not a.path:
        hub.emit("worker", f"[{worker}] not installed", task=task_id, worker=worker, ok=False)
        return {"worker": worker, "ok": False, "error": "not installed", "text": ""}
    env = {**os.environ, **_worker_env(worker, model)}
    # PWD must follow cwd. opencode resolves its working directory as
    # `path.resolve(process.env.PWD ?? process.cwd())`, PWD wins, so an
    # inherited PWD from the UI server made it edit one directory above the
    # project: files landed in the repo root, its later test/git steps saw
    # nothing, and the task still reported success. Children that trust PWD
    # over getcwd() (opencode, some shells/scripts) need this to agree.
    env["PWD"] = cwd
    last: dict = {}
    for attempt in range(1, max(1, retries) + 1):
        cmd = a.command(prompt, model, cwd)
        hub.emit(
            "worker",
            f"[{worker}] start: {prompt[:160]}" + (f" (attempt {attempt}/{retries})" if attempt > 1 else ""),
            task=task_id,
            worker=worker,
            phase="start",
            cmd=" ".join(cmd)[:400],
            model=model,
            attempt=attempt,
        )
        t0 = time.time()
        out_lines: list[str] = []
        try:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                stdin=subprocess.DEVNULL,
            )
        except Exception as e:
            hub.emit("worker", f"[{worker}] spawn failed: {e}", task=task_id, worker=worker, ok=False)
            return {"worker": worker, "ok": False, "error": str(e), "text": ""}

        q: queue.Queue = queue.Queue()

        def reader() -> None:
            try:
                for line in p.stdout:  # type: ignore[union-attr]
                    q.put(line)
            except Exception:
                pass
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()
        deadline = t0 + timeout
        buf: list[str] = []
        timed_out = False
        while True:
            try:
                item = q.get(timeout=1.0)
            except queue.Empty:
                if time.time() > deadline:
                    p.kill()
                    timed_out = True
                    hub.emit("worker", f"[{worker}] timeout after {timeout}s", task=task_id, worker=worker, ok=False)
                    break
                continue
            if item is None:
                break
            line = item.rstrip("\n")
            buf.append(line)
            if len(line.strip()) > 0:
                hub.emit("worker", f"[{worker}] {line[:500]}", task=task_id, worker=worker, phase="out")
            if time.time() > deadline:
                p.kill()
                timed_out = True
                break
        try:
            p.wait(timeout=10)
        except Exception:
            p.kill()
        raw = "\n".join(buf)
        parsed = a.parse(raw)
        dur = round(time.time() - t0, 2)
        ok = p.returncode == 0 and not timed_out
        last = {"worker": worker, "ok": ok, "rc": p.returncode, "duration": dur,
                "text": parsed.get("text") or raw[-6000:], "attempt": attempt,
                **{k: v for k, v in parsed.items() if k not in ("text",)}}
        hub.emit(
            "worker",
            f"[{worker}] {'done' if ok else 'failed'} in {dur}s",
            task=task_id,
            worker=worker,
            phase="end",
            ok=ok,
            duration=dur,
            rc=p.returncode,
            result=(parsed.get("text") or "")[-4000:],
            attempt=attempt,
        )
        if ok:
            return last
        if attempt >= retries or not _is_retryable(f"{parsed.get('text','')}\n{raw[-3000:]}"):
            break
        wait = 5 * attempt
        hub.emit("worker", f"[{worker}] transient failure, retry in {wait}s", task=task_id, worker=worker, phase="retry")
        time.sleep(wait)
    return last


class Orchestrator:
    def __init__(self) -> None:
        self.cfg = config.load()
        self.gw = Gateway(self.cfg)

    # ------------------------------------------------------------- planning
    def plan(self, prompt: str, size_hint: str = "auto") -> dict:
        cfg = config.load()
        model = cfg["gateway"].get("model")
        workers = _pick_workers(cfg, 4)
        fallback = {
            "size": "medium",
            "goal": prompt,
            "subtasks": [{"title": "Implement request", "detail": prompt, "worker": workers[0] if workers else "claude"}],
            "test_command": project.detect_test_command(),
        }
        if not model or not cfg["gateway"].get("online"):
            return fallback
        sys = (
            "You are Hermes, the orchestrator of a coding team. Classify the task and decompose it.\n"
            "Return ONLY minified JSON with keys: size (small|medium|large), goal (1 sentence), "
            "subtasks (array of {title, detail, worker} where worker is one of "
            f"{workers}), test_command (shell command or empty string).\n"
            "small = single focused edit, 1 subtask. medium = a few files, 2 subtasks. "
            "large = multi-part feature, 3-4 subtasks that can run in parallel.\n"
            "Never invent files. Keep subtask details self-contained and actionable."
        )
        r = self.gw.chat(model, [{"role": "system", "content": sys}, {"role": "user", "content": prompt}], timeout=180, max_tokens=1500)
        if not r.get("ok"):
            hub.emit("plan", f"planner LLM unavailable ({r.get('error','')[:200]}), heuristic plan", ok=False)
            return fallback
        text = r["text"].strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        try:
            start, end = text.find("{"), text.rfind("}")
            plan = json.loads(text[start : end + 1])
        except Exception:
            hub.emit("plan", "planner returned non-JSON, heuristic plan", ok=False, raw=text[:500])
            return fallback
        plan.setdefault("size", "medium")
        plan.setdefault("goal", prompt)
        plan.setdefault("subtasks", fallback["subtasks"])
        plan.setdefault("test_command", project.detect_test_command())
        # The planner tends to guess `python -m pytest`; the detected command is
        # the one that actually runs in this environment.
        detected = project.detect_test_command()
        if detected and (not plan.get("test_command") or "pytest" in str(plan.get("test_command", ""))):
            plan["test_command"] = detected
        if size_hint in ("small", "medium", "large"):
            plan["size"] = size_hint
        return plan

    # -------------------------------------------------------------- workflow
    def submit(self, prompt: str, workflow: str = "auto", workers: list[str] | None = None, model: str | None = None) -> str:
        cfg = config.load()
        tid = uuid.uuid4().hex[:12]
        t = {
            "id": tid,
            "prompt": prompt,
            "status": "running",
            "created": time.time(),
            "workflow": workflow,
            "model": model or cfg["gateway"].get("model"),
            "workers": [],
            "results": [],
        }
        with _TASK_LOCK:
            TASKS[tid] = t
        _persist_tasks()
        hub.emit("task", f"Task submitted: {prompt[:200]}", task=tid, workflow=workflow, model=t["model"], phase="created")
        threading.Thread(target=self._run, args=(tid, prompt, workflow, workers), daemon=True).start()
        return tid

    def _run(self, tid: str, prompt: str, workflow: str, workers: list[str] | None) -> None:
        t = TASKS[tid]
        try:
            cfg = config.load()
            d = project.ensure_repo()
            model = t["model"] or cfg["gateway"].get("model")
            if not model:
                raise RuntimeError("no model configured, pick one in the Gateway tab")
            t["model"] = model
            before = project.git_status()

            # --- plan -----------------------------------------------------
            if workflow in ("auto", "medium", "large"):
                hub.emit("plan", "Hermes is decomposing the task…", task=tid, phase="start")
                plan = self.plan(prompt, "auto" if workflow == "auto" else workflow)
            else:
                plan = {"size": "small", "goal": prompt, "subtasks": [{"title": prompt[:80], "detail": prompt, "worker": (workers or _pick_workers(cfg, 1))[0]}], "test_command": project.detect_test_command()}
            t["size"] = plan["size"]
            t["plan"] = plan
            hub.emit(
                "plan",
                f"size={plan['size']} · {len(plan.get('subtasks', []))} subtask(s)",
                task=tid,
                plan=plan,
                phase="end",
            )

            chosen = workers or _pick_workers(cfg, 4)
            subtasks = plan.get("subtasks") or []
            size = plan["size"]
            max_par = int(cfg["workflow"].get("max_parallel", 3))
            if size == "small":
                max_par = 1

            # --- execute --------------------------------------------------
            results: list[dict] = []
            if size == "small" or len(subtasks) <= 1:
                st = subtasks[0] if subtasks else {"title": prompt[:80], "detail": prompt, "worker": chosen[0]}
                w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
                t["workers"] = [w]
                hub.emit("worker", f"Hermes -> {w}", task=tid, worker=w, phase="assign")
                results.append(self._worker_prompt(w, st.get("detail") or st.get("title") or prompt, tid, str(d), model))
            else:
                # Large tasks run subtasks in parallel and then discuss them.
                # If the planner put every subtask on the same (cheapest) worker,
                # spread them round-robin: the discussion stage is only worth
                # anything when different CLIs actually did the work.
                if size == "large" and len({(s.get("worker") or chosen[0]) for s in subtasks}) == 1:
                    for i, s in enumerate(subtasks):
                        s["worker"] = chosen[i % len(chosen)]
                groups: list[list[dict]] = [subtasks[i : i + max_par] for i in range(0, len(subtasks), max_par)]
                for gi, group in enumerate(groups):
                    threads = []
                    box: list[dict] = []
                    hub.emit("worker", f"Hermes -> parallel batch {gi+1}: " + ", ".join(s.get("worker", "?") for s in group), task=tid, phase="assign")
                    for st in group:
                        w = st.get("worker") if st.get("worker") in adapters.ADAPTERS else chosen[0]
                        if w not in t["workers"]:
                            t["workers"].append(w)
                        thr = threading.Thread(
                            target=lambda s=st, ww=w: box.append(self._worker_prompt(ww, s.get("detail") or s.get("title"), tid, str(d), model))
                        )
                        thr.start()
                        threads.append(thr)
                    for thr in threads:
                        thr.join()
                    results.extend(box)
            t["results"] = results

            # --- escalation -------------------------------------------------
            # Every worker failed? Try one different worker before giving up:
            # the gateway routes models per provider, so a second worker often
            # succeeds when the first one's route is busy.
            if results and not any(r.get("ok") for r in results):
                alt = [w for w in chosen if w not in {r["worker"] for r in results}]
                if alt:
                    hub.emit("worker", f"all workers failed, escalating to {alt[0]}", task=tid, phase="escalate")
                    st = subtasks[0] if subtasks else {"detail": prompt}
                    if alt[0] not in t["workers"]:
                        t["workers"].append(alt[0])
                    results.append(self._worker_prompt(alt[0], st.get("detail") or prompt, tid, str(d), model))
                    t["results"] = results

            # --- discussion ----------------------------------------------
            if cfg["workflow"].get("discussion", True) and len(results) > 1:
                self._discuss(tid, prompt, results, model)

            # --- tests ----------------------------------------------------
            test_res = None
            if cfg["workflow"].get("auto_test", True):
                test_res = project.run_tests(plan.get("test_command") or None, task_id=tid)
                t["test"] = test_res
                # A red test is a work item, not an end state: hand the failure
                # back to a worker once before asking Hermes to review.
                if test_res.get("ok") is False and size != "small":
                    test_res = self._fix_failure(tid, prompt, test_res, d, model, results)
                    t["test"] = test_res

            # --- review ---------------------------------------------------
            review = None
            if cfg["workflow"].get("review", True):
                review = self._review(tid, prompt, results, test_res, model)
                t["review"] = review
                # A review that finds real issues is a work item, not an end
                # state either, hand the reviewer's own issue list back once
                # and re-review. (Green tests do not mean the task is met: a
                # worker can pass its own test while ignoring the requirement.)
                if size != "small" and (review.get("verdict") or "").upper().startswith("FAIL"):
                    fixed = self._fix_review(tid, prompt, review, d, model, results)
                    if fixed:
                        review = self._review(tid, prompt, results, t.get("test"), model)
                        t["review"] = review

            after = project.git_status()
            changed = project.change_summary(2000)
            hub.emit("git", "changes after task:\n" + (changed[:2000] or "(none)"), task=tid, diffstat=after.get("diffstat"))
            t["summary"] = self._summarize(prompt, results, test_res, review, changed)
            # Commit only work the task's own verification passed, see
            # _task_is_green. Default off; enable with workflow.auto_commit.
            if cfg["workflow"].get("auto_commit", False) and self._task_is_green(test_res, review):
                t["commit"] = self._auto_commit(tid, prompt, after.get("status") or "")
            t["status"] = "done"
            hub.emit("task", f"Task complete: {t['summary'][:200]}", task=tid, phase="done", summary=t["summary"], test_ok=(test_res or {}).get("ok"))
        except Exception as e:
            t["status"] = "error"
            t["summary"] = f"error: {e}"
            hub.emit("task", f"Task failed: {e}", task=tid, phase="error", ok=False)
        finally:
            t["finished"] = time.time()
            _persist_tasks()

    def _task_is_green(self, test_res: dict | None, review: dict | None) -> bool:
        """True only when the task's own verification actually passed.

        Committing on a FAIL review bakes known-bad work into history behind a
        tidy-looking log, and committing when nothing ran commits unverified
        work. Either way the commit stops meaning "this was checked".
        """
        if test_res is None and review is None:
            return False
        if test_res is not None and test_res.get("ok") is not True:
            return False
        if review is not None and not (review.get("verdict") or "").upper().startswith("PASS"):
            return False
        return True

    def _auto_commit(self, tid: str, prompt: str, porcelain: str) -> dict:
        """Commit a green task's changes, with the task text as the subject."""
        if not (porcelain or "").strip():
            return {"ok": True, "skipped": "no changes"}
        subject = " ".join(prompt.strip().split())
        if len(subject) > 68:
            subject = subject[:65].rstrip() + "..."
        message = f"{subject}\n\ntask: {tid}"
        res = project.git_commit_all(message)
        out = res.get("out") or ""
        ok = res.get("rc") == 0 or "nothing to commit" in out
        hub.emit("git", f"auto-commit {'ok' if ok else 'FAILED'}: {subject[:80]}",
                 task=tid, ok=ok, out=out[:300])
        return {"ok": ok, "message": message, **res}

    def _worker_prompt(self, worker: str, prompt: str, tid: str, cwd: str, model: str) -> dict:
        """Run one subtask on one worker, walking the model fallback chain.

        The chain matters more than the retry: the same prompt on the same
        worker succeeds immediately when routed to a model whose upstream is not
        saturated, so a failure here is usually routing, not capability.
        """
        cfg = config.load()
        wmodel = cfg["workers"].get(worker, {}).get("model") or model
        chain = model_chain(cfg, wmodel)
        res: dict = {}
        for i, m in enumerate(chain):
            if i:
                hub.emit("worker", f"[{worker}] retry on fallback model {m}", task=tid, worker=worker, phase="fallback", model=m)
            res = run_worker(worker, prompt, tid, cwd, m)
            if res.get("ok"):
                return res
        return res

    # ------------------------------------------------------------ fix pass
    def _fix_failure(self, tid: str, prompt: str, test_res: dict, cwd, model: str, results: list[dict]) -> dict:
        """One repair round: show a worker the failing tests and let it fix them."""
        cfg = config.load()
        if not cfg["workflow"].get("fix_on_fail", True):
            return test_res
        rounds = int(cfg["workflow"].get("fix_rounds", 1))
        for rnd in range(1, rounds + 1):
            hub.emit("test", f"tests failed, repair round {rnd}/{rounds}", task=tid, phase="fix")
            detail = (
                f"The test suite for this task is failing.\n\nTask: {prompt}\n\n"
                f"Command: {test_res.get('command')}\nrc={test_res.get('rc')}\n"
                f"Output:\n{(test_res.get('output') or '')[-3000:]}\n\n"
                "Fix the code and/or the tests so the suite passes. Do not delete or weaken tests "
                "to make them pass. Run the tests yourself before finishing."
            )
            used = {r["worker"] for r in results if r.get("ok")}
            # Cheapest first: a repair round is a small fix, not a place to
            # spend a $0.45 Claude request when omp does it for cents.
            order = _pick_cheapest(cfg, 1, exclude=used) or _pick_workers(cfg, 1)
            res = self._worker_prompt(order[0], detail, tid, str(cwd), model)
            results.append(res)
            test_res = project.run_tests(test_res.get("command") or None, task_id=tid)
            if test_res.get("ok"):
                hub.emit("test", f"tests PASS after repair round {rnd}", task=tid, ok=True)
                return test_res
        return test_res

    # ------------------------------------------------------------ review fix
    def _fix_review(self, tid: str, prompt: str, review: dict, cwd, model: str,
                    results: list[dict]) -> bool:
        """Hand the reviewer's own issue list back to a worker, once.

        Returns True when the worker actually changed something, so the caller
        only re-reviews when there is something new to look at.
        """
        cfg = config.load()
        rounds = int(cfg["workflow"].get("fix_review_rounds", 1))
        if rounds <= 0:
            return False
        before = project.change_summary(200000)
        used = {r["worker"] for r in results if r.get("ok")}
        order = _pick_cheapest(cfg, 1, exclude=used) or _pick_workers(cfg, 1)
        if not order:
            return False
        hub.emit("review", "review FAIL, sending issues back to a worker", task=tid, phase="fix")
        detail = (
            f"Task: {prompt}\n\nAn independent review of the work found these issues:\n"
            f"{review.get('text', '')[:2500]}\n\n"
            "Fix exactly these issues in the project files. Change only what the issues "
            "require, keep the tests green, and run the tests yourself before finishing."
        )
        res = self._worker_prompt(order[0], detail, tid, str(cwd), model)
        results.append(res)
        after = project.change_summary(200000)
        return after.strip() != before.strip()

    # ------------------------------------------------------------ discussion
    def _discuss(self, tid: str, prompt: str, results: list[dict], model: str) -> None:
        hub.emit("discuss", "Agents are reviewing each other's work…", task=tid, phase="start")
        digest = "\n\n".join(f"### {r['worker']} ({'ok' if r.get('ok') else 'failed'})\n{(r.get('text') or '')[-1500:]}" for r in results)
        for r in results:
            w = r["worker"]
            wmodel = config.load()["workers"].get(w, {}).get("model") or model
            others = "\n\n".join(f"### {x['worker']}\n{(x.get('text') or '')[-900:]}" for x in results if x["worker"] != w)
            msg = (
                f"Task: {prompt}\n\nYour own result:\n{(r.get('text') or '')[-1200:]}\n\n"
                f"Teammates' results:\n{others}\n\n"
                "In <=120 words: state agreement/disagreement, concrete bugs or gaps in the other work, "
                "and the single most important next fix. Be specific about files."
            )
            out = self.gw.chat(wmodel, [{"role": "user", "content": msg}], timeout=150, max_tokens=600)
            text = out.get("text") if out.get("ok") else f"(no comment: {out.get('error','')[:120]})"
            hub.emit("discuss", f"[{w}] {text[:1200]}", task=tid, worker=w, phase="msg", text=text)
        hub.emit("discuss", "Discussion round finished", task=tid, phase="end")

    # ---------------------------------------------------------------- review
    def _review(self, tid: str, prompt: str, results: list[dict], test_res: dict | None, model: str) -> dict:
        hub.emit("review", "Hermes review in progress…", task=tid, phase="start")
        diff = project.change_summary(12000)
        digest = "\n\n".join(f"### {r['worker']}\n{(r.get('text') or '')[-1200:]}" for r in results)
        tinfo = "not run"
        if test_res:
            tinfo = f"{test_res.get('command')} -> rc={test_res.get('rc')} ok={test_res.get('ok')}\n{(test_res.get('output') or '')[-1500:]}"
        msg = (
            f"Original task: {prompt}\n\nWorker reports:\n{digest}\n\nTest result:\n{tinfo}\n\n"
            f"Git diff:\n{diff}\n\n"
            "You are the orchestrator reviewing the work. Answer in this exact shape:\n"
            "VERDICT: PASS|FAIL\nISSUES: bullet list (or 'none')\nNEXT: the single next action"
        )
        out = self.gw.chat(model, [{"role": "user", "content": msg}], timeout=200, max_tokens=900)
        text = out.get("text") if out.get("ok") else f"(review unavailable: {out.get('error','')[:200]})"
        verdict = "UNKNOWN"
        for line in text.splitlines():
            if line.strip().upper().startswith("VERDICT"):
                verdict = line.split(":", 1)[-1].strip().upper()[:20]
                break
        hub.emit("review", f"verdict={verdict}", task=tid, phase="end", verdict=verdict, text=text[:4000])
        return {"verdict": verdict, "text": text}

    # --------------------------------------------------------------- summary
    def _summarize(self, prompt: str, results: list[dict], test_res: dict | None, review: dict | None, changed: str) -> str:
        parts = [f"task: {prompt[:160]}"]
        parts.append("workers: " + ", ".join(f"{r['worker']}({'ok' if r.get('ok') else 'fail'})" for r in results))
        if test_res:
            parts.append(f"tests: {'skipped' if test_res.get('skipped') else ('PASS' if test_res.get('ok') else 'FAIL')}")
        if review:
            parts.append(f"review: {review.get('verdict')}")
        files = [ln.split("---")[1].strip() for ln in (changed or "").splitlines() if ln.startswith("--- new file:")]
        if files:
            parts.append(f"new files: {', '.join(files[:6])}")
        return " · ".join(parts)
