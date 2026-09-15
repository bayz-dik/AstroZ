# curl recipes for local server-backed web apps

Copy-paste probes used to exercise routes and read session-gated feedback.

## Readiness + a GET page
```bash
U=http://127.0.0.1:5000
curl -s -o /tmp/idx.html -w "HTTP %{http_code}, %{size_download} bytes\n" $U/
grep -c 'some-marker-in-a-row' /tmp/idx.html   # count rows rendered
```

## Session-gated feedback (flash messages) — the cookie-jar form
```bash
J=/tmp/cj.txt; rm -f $J
curl -s -c $J -b $J -L -d "email=bad&subject=x" $U/daftar/add | grep -o 'Email tidak valid[^<]*'
```
Without `-c $J -b $J` the followed redirect renders no message. `-L` follows the POST->redirect->GET.

## A write route, asserting the on-disk result
```bash
cp daftar.csv /tmp/daftar.backup.csv
curl -s -o /dev/null -w "HTTP %{http_code}\n" -d "no=1" $U/daftar/delete
cat daftar.csv                         # assert the row is gone
cp /tmp/daftar.backup.csv daftar.csv   # restore
```

## Multi-line textarea POST (editor save)
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" \
  --data-urlencode $'daftar_text=email,subject,cv\nhrd@x.com,Lamaran X,\n' $U/daftar/save
```

## File-upload route
```bash
printf 'email,subject,cv\nhrd@imp.com,Lamaran Impor,\n' > /tmp/impor.csv
curl -s -c $J -b $J -L -F "csv_file=@/tmp/impor.csv" $U/daftar/upload | grep -o 'diganti dari file[^<]*'
```

## Start / stop
```bash
# start (terminal tool, background=True)
cd <dir> && source .venv/bin/activate && python app.py > /tmp/app.log 2>&1
# stop: read the PID, kill the PID
pgrep -af "app.py"      # take the real python PID, not the shell's
kill <pid>
```
