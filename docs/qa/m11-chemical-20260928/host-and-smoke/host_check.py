"""Raw-socket Host header checks against live loopback :3000 and :8000 (no non-loopback traffic)."""
import json, socket, sys, hashlib, datetime
backend_log = sys.argv[1]; out = sys.argv[2]
def raw(port, path, host_lines):
    req = f"GET {path} HTTP/1.1\r\n" + "".join(f"Host: {h}\r\n" for h in host_lines) + "Connection: close\r\n\r\n"
    s = socket.create_connection(("127.0.0.1", port), timeout=30); s.sendall(req.encode())
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk: break
        data += chunk
    s.close()
    head, _, body = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode(errors="replace")
    return status, body[:300].decode(errors="replace"), hashlib.sha256(body).hexdigest(), len(body)
def backend_lines():
    return open(backend_log, errors="replace").read().count("\n")
cases = [
  ("spoofed", ["evil.example"]), ("spoofed-with-port", ["evil.example:3000"]),
  ("allowed-127", ["127.0.0.1:{port}"]), ("allowed-localhost-upper", ["LOCALHOST:{port}"]), ("allowed-ipv6", ["[::1]:{port}"]),
  ("missing", []), ("two-hosts-allowed-then-foreign", ["127.0.0.1:{port}", "evil.example"]),
  ("two-hosts-foreign-then-allowed", ["evil.example", "127.0.0.1:{port}"]), ("two-hosts-both-allowed", ["127.0.0.1:{port}", "localhost:{port}"]),
]
results = []
for port, paths in ((3000, ["/api/capabilities", "/"]), (8000, ["/capabilities"])):
    for path in paths:
        for name, hosts in cases:
            hosts = [h.format(port=port) for h in hosts]
            before = backend_lines()
            status, body, sha, n = raw(port, path, hosts)
            import time; time.sleep(0.3)
            after = backend_lines()
            results.append({"port": port, "path": path, "case": name, "hostHeaders": hosts, "statusLine": status,
                            "bodyPrefix": body if status.split()[1] in ("400", "404") or n < 200 else body[:120],
                            "bodyBytes": n, "bodySha256": sha, "backendLogLinesAdded": after - before})
json.dump({"recordedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "results": results}, open(out, "w"), indent=2)
for r in results: print(r["port"], r["path"], r["case"], r["statusLine"], "backendLog+%d" % r["backendLogLinesAdded"])
