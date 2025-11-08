# app.py
import os
import sys
import json
import time
import argparse
from typing import Dict, Any, List, Tuple, Optional
from web3 import Web3
from eth_utils import keccak

DEFAULT_RPC = os.environ.get("RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_KEY")

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_event_signature_map(abi: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Returns a map: topic_hash (0x...) -> {name, inputs, signature}
    """
    topic_map: Dict[str, Dict[str, Any]] = {}
    for item in abi:
        if item.get("type") != "event":
            continue
        name = item.get("name")
        inputs = item.get("inputs", [])
        if not name or not isinstance(inputs, list):
            continue
        arg_types = ",".join(i["type"] for i in inputs)
        signature = f"{name}({arg_types})"
        topic = "0x" + keccak(text=signature).hex()
        topic_map[topic] = {"name": name, "inputs": inputs, "signature": signature}
    return topic_map

def chunk_ranges(start: int, end: int, step: int) -> List[Tuple[int, int]]:
    """
    Inclusive chunking: (start, end) inclusive, split into step-sized ranges.
    """
    ranges = []
    cur = start
    while cur <= end:
        rng_end = min(cur + step - 1, end)
        ranges.append((cur, rng_end))
        cur = rng_end + 1
    return ranges

def fetch_logs(w3: Web3, address: str, from_block: int, to_block: int, step: int) -> List[Dict[str, Any]]:
    """
    Fetch logs for address across [from_block, to_block] in chunks to avoid provider limits.
    """
    all_logs: List[Dict[str, Any]] = []
    for a, b in chunk_ranges(from_block, to_block, step):
        logs = w3.eth.get_logs({
            "address": Web3.to_checksum_address(address),
            "fromBlock": a,
            "toBlock": b
        })
        all_logs.extend(logs)
    return all_logs

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="event-soundness — verify event topics emitted by a contract over a block range match an ABI (useful for Aztec/Zama bridges, rollups, and general Web3 soundness checks)."
    )
    p.add_argument("--rpc", default=DEFAULT_RPC, help="EVM RPC URL (default from RPC_URL)")
    p.add_argument("--address", required=True, help="Contract address to analyze")
    p.add_argument("--abi", required=True, help="Path to ABI JSON file containing event definitions")
    p.add_argument("--from-block", type=int, required=False, help="Start block (inclusive)")
    p.add_argument("--to-block", type=int, required=False, help="End block (inclusive)")
    p.add_argument("--step", type=int, default=2_000, help="Block chunk size for log queries (default: 2000)")
    p.add_argument("--expected-events", help="JSON file with required event names (array of strings)")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    p.add_argument("--timeout", type=int, default=30, help="RPC timeout seconds (default: 30)")
    return p.parse_args()

def main() -> None:
    start_time = time.time()
    args = parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc, request_kwargs={"timeout": args.timeout}))
    if not w3.is_connected():
        print("❌ RPC connection failed. Check RPC_URL or --rpc.")
        sys.exit(1)
    print("🔧 event-soundness (event topic interface auditor)")
    print(f"🔗 RPC: {args.rpc}")

    try:
        chain_id = w3.eth.chain_id
        print(f"🧭 Chain ID: {chain_id}")
    except Exception:
        chain_id = None

    # Determine block range
    latest = w3.eth.block_number
    from_block = args.from_block if args.from_block is not None else max(0, latest - 5000)
    to_block = args.to_block if args.to_block is not None else latest
    if from_block > to_block:
        print("❌ Invalid range: from-block must be <= to-block.")
        sys.exit(1)

    print(f"🏷️ Address: {Web3.to_checksum_address(args.address)}")
    print(f"🧱 Blocks: {from_block} → {to_block} (step={args.step})")

    # Load ABI and construct expected topics
    try:
        abi = load_json(args.abi)
        if not isinstance(abi, list):
            raise ValueError("ABI must be a JSON array.")
    except Exception as e:
        print(f"❌ Failed to load ABI: {e}")
        sys.exit(1)

    topic_map = build_event_signature_map(abi)
    if not topic_map:
        print("⚠️ No events found in ABI; nothing to verify against.")
    # Optional expected event names
    required_events: Optional[List[str]] = None
    if args.expected_events:
        try:
            required_events = load_json(args.expected_events)
            if not isinstance(required_events, list) or not all(isinstance(x, str) for x in required_events):
                raise ValueError("expected-events must be a JSON array of strings.")
        except Exception as e:
            print(f"❌ Failed to load expected events: {e}")
            sys.exit(1)

    # Fetch logs
    try:
        logs = fetch_logs(w3, args.address, from_block, to_block, max(1, args.step))
    except Exception as e:
        print(f"❌ Failed to fetch logs: {e}")
        sys.exit(1)

    print(f"📰 Logs fetched: {len(logs)}")

    # Analyze topics
    counts_by_topic: Dict[str, int] = {}
    unknown_topics: Dict[str, int] = {}
    for lg in logs:
        topics = [Web3.to_hex(t) for t in lg.get("topics", [])]
        if not topics:
            continue
        t0 = topics[0]
        counts_by_topic[t0] = counts_by_topic.get(t0, 0) + 1
        if t0 not in topic_map:
            unknown_topics[t0] = unknown_topics.get(t0, 0) + 1

    # Map topic->name for report
    counts_by_name: Dict[str, int] = {}
    for topic, cnt in counts_by_topic.items():
        name = topic_map.get(topic, {}).get("name", f"UNKNOWN({topic[:10]}…)")  # fallback
        counts_by_name[name] = counts_by_name.get(name, 0) + cnt

    # Required events check
    missing_required: List[str] = []
    if required_events:
        present_names = set(n for n in counts_by_name.keys() if not n.startswith("UNKNOWN("))
        for req in required_events:
            if req not in present_names:
                missing_required.append(req)

    # Output (human)
    if counts_by_name:
        print("📊 Event counts (by name):")
        for name in sorted(counts_by_name.keys()):
            print(f"   • {name}: {counts_by_name[name]}")
    else:
        print("⚠️ No events observed in the given range.")

    if unknown_topics:
        print(f"🚩 Unknown topics (not in ABI): {len(unknown_topics)}")
        sample = ", ".join(list(unknown_topics.keys())[:10])
        print(f"   sample: {sample}{' ...' if len(unknown_topics) > 10 else ''}")
    else:
        print("✅ No unknown event topics detected.")

    if missing_required:
        print(f"❌ Missing required events: {', '.join(missing_required)}")
    elif required_events is not None:
        print("✅ All required events were observed at least once.")

    elapsed = time.time() - start_time
    print(f"⏱️ Completed in {elapsed:.2f}s")

    # JSON output
    if args.json:
        out = {
            "rpc": args.rpc,
            "chain_id": chain_id,
            "address": Web3.to_checksum_address(args.address),
            "from_block": from_block,
            "to_block": to_block,
            "logs_fetched": len(logs),
            "counts_by_topic": counts_by_topic,
            "counts_by_name": counts_by_name,
            "unknown_topics": unknown_topics,
            "required_events": required_events,
            "missing_required": missing_required,
            "elapsed_seconds": round(elapsed, 2),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))

    # Exit code policy:
    # - Unknown topics OR missing required events => 2
    # - Otherwise 0
    bad = bool(unknown_topics) or bool(missing_required)
    sys.exit(2 if bad else 0)

if __name__ == "__main__":
    main()
