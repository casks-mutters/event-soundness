# event-soundness

# Overview
A lightweight CLI that audits a contract’s emitted events over a block range and verifies they match your ABI. It flags unknown topics (not present in the ABI) and can assert that certain “required” events were observed. This is useful for monitoring L1 contracts connected to privacy/zk ecosystems (e.g., Aztec bridges, ZK rollup registries, or Zama-integrated flows), where interface soundness and upgrade safety matter.

# What it checks
1) Computes canonical event topics (keccak of `EventName(types)`) from your ABI.
2) Fetches logs for the contract across a chosen block range.
3) Counts events by topic and name.
4) Reports any unknown topics not in your ABI.
5) Optionally checks that specific required events were observed at least once.

# Installation
1) Requires Python 3.9+
2) Install dependencies:
   pip install web3 eth-utils
3) Set an RPC endpoint (or pass `--rpc` each run):
   export RPC_URL=https://mainnet.infura.io/v3/YOUR_KEY

# Usage
Basic scan over the last ~5000 blocks (default if range omitted):
   python app.py --address 0xYourContract --abi ./YourContract.abi.json

Explicit block range:
   python app.py --address 0xYourContract --abi ./YourContract.abi.json --from-block 20000000 --to-block 20005000

Chunk size (provider-friendly):
   python app.py --address 0xYourContract --abi ./YourContract.abi.json --from-block 20000000 --to-block 20020000 --step 1500

Require certain events to appear:
   python app.py --address 0xYourContract --abi ./YourContract.abi.json --expected-events required.json

Emit JSON for CI pipelines:
   python app.py --address 0xYourContract --abi ./YourContract.abi.json --from-block 20000000 --to-block 20010000 --json

required.json format
A JSON array of event names that must be observed at least once in the range:
["Transfer", "Approval", "BridgeFinalized"]

# Expected output
- Summary of RPC, chain id, address, and block range  
- Count of logs fetched and events by name  
- Unknown topics (if any) with a small sample  
- Required events check status  
- Exit code 0 when clean, 2 if unknown topics or a required event is missing
