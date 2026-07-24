from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

OUT = Path(os.environ.get("IXO_3948_OUT", "artifacts/ixo-3948"))
CHAIN_ID = os.environ.get("CHAIN_ID", "ixo-5")
TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "20"))
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "IXO-M1-Research/1.0 (+https://linear.app/ixo-world/issue/IXO-3948)",
}

for rel in ["raw/genesis", "raw/current/rpc", "raw/current/rest", "cleaned", "derived", "hashes", "logs"]:
    (OUT / rel).mkdir(parents=True, exist_ok=True)


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def log(method: str, url: str, headers: dict[str, str] | None = None) -> None:
    with (OUT / "logs/commands.log").open("a", encoding="utf-8") as handle:
        handle.write(" | ".join([method, url] + [f"{k}: {v}" for k, v in sorted((headers or {}).items())]) + "\n")


def status(name: str, endpoint: str, ok: bool, detail: str = "") -> None:
    with (OUT / "query-status.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "endpoint": endpoint, "ok": ok, "detail": detail}, sort_keys=True) + "\n")


def fetch(url: str, *, headers: dict[str, str] | None = None, retries: int = 1) -> tuple[int, dict[str, str], bytes]:
    merged = dict(HEADERS)
    merged.update(headers or {})
    log("GET", url, headers)
    last: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=merged, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
        except Exception as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    return 0, {}, f"{type(last).__name__}: {last}".encode()


def save(path: Path, body: bytes, headers: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if headers is not None:
        path.with_suffix(".headers").write_text("".join(f"{k}: {v}\n" for k, v in sorted(headers.items())), encoding="utf-8")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def iter_coins(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        if "denom" in payload and "amount" in payload:
            yield payload
        else:
            for value in payload.values():
                yield from iter_coins(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_coins(value)


def uixo(payload: Any) -> Decimal:
    return sum((dec(coin.get("amount")) for coin in iter_coins(payload) if coin.get("denom") == "uixo"), Decimal(0))


def account_address(account: dict[str, Any]) -> str:
    stack = [account]
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if isinstance(address, str) and address.startswith("ixo1"):
            return address
        for key in ("base_account", "base_vesting_account"):
            if isinstance(item.get(key), dict):
                stack.append(item[key])
    return ""


def technical_class(account_type: str, module: bool = False) -> str:
    if module or "ModuleAccount" in account_type:
        return "protocol-module"
    if "VestingAccount" in account_type:
        return "vesting-account"
    if "ContractAccount" in account_type:
        return "contract-account"
    return "ordinary-or-unknown"


def distribution_metrics(amounts: list[Decimal], denominator: Decimal | None = None) -> dict[str, Any]:
    values = sorted((value for value in amounts if value > 0), reverse=True)
    total = denominator if denominator is not None else sum(values, Decimal(0))
    shares = [(value / total) if total else Decimal(0) for value in values]
    result: dict[str, Any] = {
        "positive_address_count": len(values),
        "sum_uixo": str(sum(values, Decimal(0))),
        "denominator_uixo": str(total),
        "hhi": str(sum((share * share for share in shares), Decimal(0))),
    }
    for count in (1, 3, 5, 10, 20, 50, 100):
        result[f"top_{count}_share"] = str(sum(shares[:count], Decimal(0)))
    return result


def hash_tree() -> str:
    lines = []
    target = OUT / "hashes/sha256sums.txt"
    for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p != target):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(OUT).as_posix()}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()
