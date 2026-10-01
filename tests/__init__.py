"""测试只许连临时库（replan §11，serenity 的硬防线）：置位后连 data/market.sqlite 或 data/ledger.sqlite 一律报错。"""
import os

os.environ["ETF_LEDGER_TESTING"] = "1"
