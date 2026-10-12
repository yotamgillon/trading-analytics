from trading_analytics.demo import write_demo

demo = write_demo()
print(
    f"Wrote demo data: {len(demo.raw_fills)} fills, {len(demo.truth_trades)} trades, "
    f"{len(demo.bars_1m)} bars -> data/demo/"
)
