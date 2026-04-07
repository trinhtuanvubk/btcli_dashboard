import bittensor as bt

subtensor = bt.Subtensor(network="finney")
metagraph = subtensor.metagraph(netuid=82)

print("=== Metagraph attributes ===")
for attr in sorted(dir(metagraph)):
    if attr.startswith("_"):
        continue
    try:
        val = getattr(metagraph, attr)
        if callable(val):
            continue
        type_name = type(val).__name__
        if hasattr(val, "shape"):
            print(f"  {attr:20s}  type={type_name}  shape={val.shape}")
        elif isinstance(val, list) and len(val) > 0:
            print(f"  {attr:20s}  type=list[{type(val[0]).__name__}]  len={len(val)}")
        else:
            print(f"  {attr:20s}  type={type_name}  value={val}")
    except Exception as e:
        print(f"  {attr:20s}  ERROR: {e}")

print("\n=== First axon object attributes ===")
axon0 = metagraph.axons[0]
for attr in sorted(dir(axon0)):
    if attr.startswith("_"):
        continue
    try:
        val = getattr(axon0, attr)
        if callable(val):
            continue
        print(f"  {attr:20s} = {val!r}")
    except Exception as e:
        print(f"  {attr:20s}  ERROR: {e}")

print("\n=== Sample: top 10 by incentive ===")
incentives = metagraph.incentive.tolist()
ranked = sorted(enumerate(incentives), key=lambda x: x[1], reverse=True)[:10]

header = f"{'RANK':>4}  {'UID':>5}  {'INCENTIVE':>12}  {'TRUST':>10}  {'EMISSION':>12}  {'STAKE':>14}  {'HOTKEY':42}  {'AXON_IP':>15}  {'AXON_PORT':>9}"
print(header)
print("-" * len(header))
for rank, (uid, inc) in enumerate(ranked, start=1):
    axon = metagraph.axons[uid]
    print(
        f"{rank:4d}  {uid:5d}  {inc:12.6f}"
        f"  {metagraph.trust[uid].item():10.6f}"
        f"  {metagraph.emission[uid].item():12.6f}"
        f"  {metagraph.stake[uid].item():14.4f}"
        f"  {axon.hotkey:42}"
        f"  {axon.ip:>15}:{axon.port}"
    )
