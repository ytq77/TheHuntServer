"""Protocol smoke test against this runner's isolated Linux Compose deployment."""
import argparse
import base64
import json
import socket
import struct
import time
import urllib.request
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument("--server-ip", required=True)
address = parser.parse_args().server_ip
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get(port, path):
    with opener.open(f"http://{address}:{port}{path}", timeout=3) as response:
        return response.read()

for _ in range(60):
    try:
        assert json.loads(get(31415, "/status"))["ok"] is True
        xml = base64.b64decode(get(20443, "/bb-eu/ss.info")).decode()
        break
    except OSError:
        time.sleep(1)
else:
    raise AssertionError("Linux services did not become ready")
doc = ET.fromstring("<root>" + xml + "</root>")
for tag in ("SummonDataGetListInterval2", "SummonDataCreateInterval2"):
    assert [e.text for e in doc.iter(tag)] == ["2"], tag
summons = [e.text for e in doc.iter() if e.tag.startswith("api_SummonData")]
assert len(summons) == 4 and all(url == f"http://{address}:31415" for url in summons), summons
login = next(e.text for e in doc.iter() if e.tag == "api_Login")
assert login == f"http://{address}:20443", login
request = urllib.request.Request(login + "/basic_utils/login", data=b'{"MessageId":"LoginRequest"}',
                                 headers={"Content-Type": "application/json"})
with opener.open(request, timeout=3) as response:
    assert json.load(response)["ResKind"] == 0
for prefix in (bytes.fromhex("ffffffff"), bytes.fromhex("ff83ffffffff")):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.bind((address, 0))
        connection.settimeout(3)
        expected = socket.inet_aton(address) + struct.pack("!H", connection.getsockname()[1])
        connection.sendto(prefix + b"\x01" + b"linux-test".ljust(16, b"\0") + socket.inet_aton(address),
                          (address, 31414))
        reply, _ = connection.recvfrom(1024)
        assert reply == prefix + expected, reply.hex()
with socket.create_connection((address, 20444), timeout=3):
    pass
print("PASS: Linux status, login, 2-second summon intervals, isolated summon routes, STUN 4/6 framing and relay listener")
