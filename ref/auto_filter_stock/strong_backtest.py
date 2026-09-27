#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正后的回测逻辑 - 正确的调仓机制
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from datetime import date
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

class CorrectBacktestEngine:
    def __init__(self):
        # 交易成本参数 - 修正后的参数
        self.commission_rate = 0.000086  # 手续费率 0.0086%
        self.slippage_rate = 0.001  # 滑点率 0.1%
        self.min_commission = 5.0  # 最低手续费5元
        self.initial_capital = 1000000
        
        self.trading_data = None
        self.screening_data = None
        
    def load_data(self):
        """加载数据"""
        print("加载筛选结果...")
        self.screening_data = pd.read_csv('data/daily_screening_results.csv')
        self.screening_data['筛选日期'] = pd.to_datetime(self.screening_data['筛选日期']).dt.date
        
        print("加载交易数据...")
        self.trading_data = pd.read_stata('data/trading_data.dta')
        self.trading_data['Trddt'] = pd.to_datetime(self.trading_data['Trddt']).dt.date
        self.trading_data.set_index(['Stkcd', 'Trddt'], inplace=True)
        
        # 交易日对齐检查
        self._validate_trading_day_alignment()
    
    def _validate_trading_day_alignment(self):
        """验证交易日对齐"""
        screening_dates = set(self.screening_data['筛选日期'].unique())
        trading_dates = set(self.trading_data.index.get_level_values('Trddt').unique())
        
        # 检查筛选日期是否都在交易日期中
        missing_trading_dates = screening_dates - trading_dates
        if missing_trading_dates:
            print(f"⚠️  警告: 发现{len(missing_trading_dates)}个筛选日期不在交易数据中:")
            for date in sorted(missing_trading_dates)[:5]:  # 只显示前5个
                print(f"    {date}")
            if len(missing_trading_dates) > 5:
                print(f"    ... 还有{len(missing_trading_dates) - 5}个日期")
            print("    这些日期将使用买入价作为备用价格")
        
        # 检查交易日期是否都在筛选日期中
        missing_screening_dates = trading_dates - screening_dates
        if missing_screening_dates:
            print(f"ℹ️  信息: 发现{len(missing_screening_dates)}个交易日期不在筛选数据中")
        
        print(f"✅ 数据对齐检查完成: 筛选日期{len(screening_dates)}个, 交易日期{len(trading_dates)}个")
        
    def convert_stock_code(self, code_str):
        """转换股票代码格式"""
        if '.' in code_str:
            return code_str.split('.')[0]
        return str(code_str)
    
    def get_stock_price(self, stock_symbol, target_date, price_type='close'):
        """获取股票价格 - 改进的健壮性处理"""
        converted_symbol = self.convert_stock_code(stock_symbol)
        try:
            stock_data = self.trading_data.loc[(converted_symbol, target_date)]
            
            # 处理多行数据的情况
            if isinstance(stock_data, pd.DataFrame):
                # 如果有多行，取第一行（通常是主数据）
                stock_data = stock_data.iloc[0]
            
            if price_type == 'open':
                price = stock_data['Opnprc']
            elif price_type == 'close':
                price = stock_data['Clsprc']
            elif price_type == 'high':
                price = stock_data['Hiprc']
            elif price_type == 'low':
                price = stock_data['Loprc']
            elif price_type == 'average':
                # 平均价 = (最高价 + 最低价) / 2
                high_price = stock_data['Hiprc']
                low_price = stock_data['Loprc']
                if pd.isna(high_price) or pd.isna(low_price) or high_price <= 0 or low_price <= 0:
                    return 0.0
                price = (high_price + low_price) / 2
            else:
                price = stock_data['Clsprc']
            
            # 更严格的价格验证
            if pd.isna(price) or price <= 0:
                return 0.0
            
            return float(price)
        except (KeyError, IndexError, TypeError, ValueError):
            # 更具体的异常处理
            return 0.0
    
    def run_backtest(self, holding_days):
        """运行回测 - 正确的调仓逻辑"""
        print(f"运行{holding_days}天策略回测...")
        
        trading_dates = sorted(self.screening_data['筛选日期'].unique())
        
        # 创建日期到索引的映射，提高查找效率
        date_to_index = {date: idx for idx, date in enumerate(trading_dates)}
        
        # 初始化状态
        current_cash = self.initial_capital
        current_positions = {}  # {stock_symbol: {quantity, buy_price, buy_date}}
        daily_values = []
        
        # 交易日志
        trade_log = []
        
        i = 0
        while i < len(trading_dates):
            trade_date = trading_dates[i]
            
            if i % 20 == 0:
                print(f"  处理进度: {i+1}/{len(trading_dates)}")
            
            # 1. 先检查是否需要卖出（T+1日卖出，使用平均价）
            sold_stocks = []
            if current_positions:
                first_position = list(current_positions.values())[0]
                buy_date = first_position['buy_date']
                buy_date_idx = date_to_index[buy_date]
                
                # 持有期判断：T日买入，T+1日卖出 = 持有1天
                if i - buy_date_idx == holding_days:
                    # 在T+1日卖出，使用平均价
                    total_sell_value = 0
                    for stock_symbol, position in current_positions.items():
                        # 使用T+1日的平均价（最高价+最低价）/2
                        average_price = self.get_stock_price(stock_symbol, trade_date, 'average')
                        if average_price == 0:
                            average_price = position['buy_price']  # 使用买入价作为备用
                        
                        # 应用滑点
                        actual_sell_price = average_price * (1 - self.slippage_rate)
                        sell_amount = position['quantity'] * actual_sell_price
                        commission = max(sell_amount * self.commission_rate, self.min_commission)
                        net_amount = sell_amount - commission
                        total_sell_value += net_amount
                        
                        # 记录卖出
                        sold_stocks.append({
                            'symbol': stock_symbol,
                            'name': position['name'],
                            'quantity': position['quantity'],
                            'sell_price': actual_sell_price,
                            'sell_amount': sell_amount,
                            'commission': commission,
                            'net_amount': net_amount
                        })
                    
                    # 累加现金
                    current_cash += total_sell_value
                    current_positions = {}
            
            # 2. 检查是否需要买入新股票
            need_buy = False
            if not current_positions:
                need_buy = True
            
            # 记录操作状态（简化日志输出）
            if i % 20 == 0:  # 每20天记录一次
                if need_buy:
                    print(f"    {trade_date}: 需要买入新股票")
                else:
                    print(f"    {trade_date}: 有持仓，不买入")
            
            # 记录买入的股票
            bought_stocks = []
            if need_buy:
                # 使用T-1日筛选的强势股（T日买入）
                if i > 0:
                    screening_date = trading_dates[i - 1]  # T-1日筛选
                else:
                    screening_date = trade_date  # 第一天使用当日筛选
                
                daily_stocks = self.screening_data[
                    self.screening_data['筛选日期'] == screening_date
                ].sort_values('排名').head(10)
                
                # 找出可以买入的股票
                valid_stocks = []
                for _, stock in daily_stocks.iterrows():
                    stock_symbol = stock['股票代码']
                    open_price = self.get_stock_price(stock_symbol, trade_date, 'open')
                    
                    # 数据缺失处理：开盘价为0表示数据缺失，直接跳过
                    if open_price == 0:
                        continue  # 跳过数据缺失的股票，不买入
                    
                    # 数据缺失处理：如果开盘价不可用，尝试使用前一日收盘价
                    if pd.isna(open_price) and i > 0:
                        prev_date = trading_dates[i - 1]
                        open_price = self.get_stock_price(stock_symbol, prev_date, 'close')
                        # 如果前一日收盘价也为0或缺失，跳过该股票
                        if open_price == 0 or pd.isna(open_price):
                            continue
                    
                    # 只有有效价格（>0）的股票才能买入
                    if open_price > 0:
                        # 涨停股判断：开盘价 = 最高价 = 最低价 = 收盘价
                        high_price = self.get_stock_price(stock_symbol, trade_date, 'high')
                        low_price = self.get_stock_price(stock_symbol, trade_date, 'low')
                        close_price = self.get_stock_price(stock_symbol, trade_date, 'close')
                        
                        # 如果开盘价等于最高价等于最低价，可能是涨停股，跳过
                        if (high_price > 0 and low_price > 0 and 
                            abs(open_price - high_price) < 0.01 and 
                            abs(open_price - low_price) < 0.01):
                            continue  # 跳过涨停股，不买入
                        
                        # 应用滑点
                        actual_buy_price = open_price * (1 + self.slippage_rate)
                        valid_stocks.append({
                            'symbol': stock_symbol,
                            'name': stock['股票名称'],
                            'price': actual_buy_price
                        })
                
                # 等权重买入（涨停股资金重新分配给其他股票）
                if valid_stocks and current_cash > 0:
                    # 计算每支有效股票的分配资金
                    cash_per_stock = current_cash / len(valid_stocks)
                    total_used_cash = 0
                    successful_purchases = 0
                    
                    for stock_info in valid_stocks:
                        quantity = int(cash_per_stock / stock_info['price'] / 100) * 100
                        if quantity > 0:
                            buy_amount = quantity * stock_info['price']
                            commission = max(buy_amount * self.commission_rate, self.min_commission)
                            total_cost = buy_amount + commission
                            
                            if total_cost <= current_cash - total_used_cash:
                                current_positions[stock_info['symbol']] = {
                                    'quantity': quantity,
                                    'buy_price': stock_info['price'],
                                    'buy_date': trade_date,
                                    'name': stock_info['name']
                                }
                                total_used_cash += total_cost
                                successful_purchases += 1
                                
                                # 记录买入
                                bought_stocks.append({
                                    'symbol': stock_info['symbol'],
                                    'name': stock_info['name'],
                                    'quantity': quantity,
                                    'buy_price': stock_info['price'],
                                    'buy_amount': buy_amount,
                                    'commission': commission,
                                    'total_cost': total_cost
                                })
                    
                    current_cash -= total_used_cash
                    
                    # 记录买入信息（简化日志输出）
                    if i % 20 == 0:  # 每20天记录一次
                        skipped_stocks = 10 - len(valid_stocks)  # 跳过的股票数量（主要是涨停股）
                        if skipped_stocks > 0:
                            print(f"    {trade_date}: 成功买入{successful_purchases}只股票, 跳过{skipped_stocks}只股票(涨停), 剩余现金{current_cash:,.0f}元")
                        else:
                            print(f"    {trade_date}: 成功买入{successful_purchases}只股票, 剩余现金{current_cash:,.0f}元")
                elif not valid_stocks:
                    if i % 20 == 0:
                        print(f"    {trade_date}: 无有效股票可买入")
            
            # 计算当前投资组合价值
            total_position_value = 0
            for stock_symbol, position in current_positions.items():
                current_price = self.get_stock_price(stock_symbol, trade_date, 'close')
                if current_price == 0:
                    current_price = position['buy_price']
                total_position_value += position['quantity'] * current_price
            
            total_value = current_cash + total_position_value
            daily_values.append(total_value)
            
            # 记录每日交易日志
            trade_log.append({
                'date': trade_date,
                'day': i + 1,
                'sold_stocks': sold_stocks,
                'bought_stocks': bought_stocks,
                'current_positions': dict(current_positions),
                'cash': current_cash,
                'position_value': total_position_value,
                'total_value': total_value
            })
            
            i += 1
        
        # 构建结果DataFrame
        returns_data = []
        for i, (date, value) in enumerate(zip(trading_dates, daily_values)):
            cumulative_return = (value / self.initial_capital) - 1
            returns_data.append({
                'date': date,
                'total_value': value,
                'cumulative_returns': cumulative_return
            })
        
        return pd.DataFrame(returns_data), trade_log
    
    def save_trade_log_to_csv(self, trade_log, strategy_name, output_dir):
        """将交易日志保存到CSV文件"""
        # 创建详细的交易记录
        detailed_records = []
        
        for log in trade_log:
            date = log['date']
            day = log['day']
            cash = log['cash']
            position_value = log['position_value']
            total_value = log['total_value']
            
            # 记录卖出交易
            for stock in log['sold_stocks']:
                detailed_records.append({
                    '日期': date,
                    '天数': day,
                    '操作类型': '卖出',
                    '股票代码': stock['symbol'],
                    '股票名称': stock['name'],
                    '数量': stock['quantity'],
                    '价格': stock['sell_price'],
                    '金额': stock['sell_amount'],
                    '手续费': stock['commission'],
                    '净收入': stock['net_amount'],
                    '现金余额': cash,
                    '持仓价值': position_value,
                    '总价值': total_value
                })
            
            # 记录买入交易
            for stock in log['bought_stocks']:
                detailed_records.append({
                    '日期': date,
                    '天数': day,
                    '操作类型': '买入',
                    '股票代码': stock['symbol'],
                    '股票名称': stock['name'],
                    '数量': stock['quantity'],
                    '价格': stock['buy_price'],
                    '金额': stock['buy_amount'],
                    '手续费': stock['commission'],
                    '净收入': -stock['total_cost'],  # 买入是负收入
                    '现金余额': cash,
                    '持仓价值': position_value,
                    '总价值': total_value
                })
            
            # 如果没有交易，记录持仓状态
            if not log['sold_stocks'] and not log['bought_stocks']:
                detailed_records.append({
                    '日期': date,
                    '天数': day,
                    '操作类型': '持仓',
                    '股票代码': '',
                    '股票名称': '',
                    '数量': 0,
                    '价格': 0,
                    '金额': 0,
                    '手续费': 0,
                    '净收入': 0,
                    '现金余额': cash,
                    '持仓价值': position_value,
                    '总价值': total_value
                })
        
        # 保存到CSV
        df = pd.DataFrame(detailed_records)
        csv_path = output_dir / f'{strategy_name}_详细交易记录.csv'
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✅ {strategy_name}详细交易记录已保存到: {csv_path}")
        
        return csv_path
    
    def calculate_performance_metrics(self, result_df, trade_log, strategy_name):
        """计算性能指标"""
        # 基础指标
        total_return = result_df['cumulative_returns'].iloc[-1]
        total_days = len(result_df)
        
        # 计算日收益率
        daily_returns = result_df['cumulative_returns'].diff().fillna(0)
        
        # 胜率计算
        winning_days = (daily_returns > 0).sum()
        win_rate = winning_days / total_days * 100
        
        # 夏普比率 (简化版，假设无风险利率为0)
        if daily_returns.std() > 0:
            sharpe_ratio = daily_returns.mean() / daily_returns.std() * (252 ** 0.5)
        else:
            sharpe_ratio = 0
        
        # 最大回撤
        cumulative_max = result_df['cumulative_returns'].expanding().max()
        drawdown = result_df['cumulative_returns'] - cumulative_max
        max_drawdown = abs(drawdown.min())
        
        # 交易统计
        total_trades = 0
        winning_trades = 0
        for log in trade_log:
            if log['sold_stocks']:
                total_trades += len(log['sold_stocks'])
                for stock in log['sold_stocks']:
                    # 计算单笔交易收益
                    buy_price = 0
                    for pos in log['current_positions'].values():
                        if pos.get('symbol') == stock['symbol']:
                            buy_price = pos.get('buy_price', 0)
                            break
                    
                    if buy_price > 0:
                        trade_return = (stock['sell_price'] - buy_price) / buy_price
                        if trade_return > 0:
                            winning_trades += 1
        
        trade_win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        return {
            'strategy': strategy_name,
            'total_return': total_return * 100,
            'win_rate': win_rate,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown * 100,
            'total_trades': total_trades,
            'trade_win_rate': trade_win_rate
        }

def load_cs300_benchmark(start_date, end_date):
    """加载沪深300基准数据"""
    try:
        print("加载沪深300基准数据...")
        cs300_data = pd.read_stata('data/CS300.dta')
        cs300_data['Trddt'] = pd.to_datetime(cs300_data['Trddt']).dt.date
        
        benchmark_data = cs300_data[
            (cs300_data['Trddt'] >= start_date) & 
            (cs300_data['Trddt'] <= end_date)
        ].sort_values('Trddt')
        
        if not benchmark_data.empty:
            initial_price = benchmark_data.iloc[0]['Clsindex']
            benchmark_data['cumulative_returns'] = (benchmark_data['Clsindex'] / initial_price) - 1
            
            return pd.DataFrame({
                'date': benchmark_data['Trddt'].tolist(),
                'cumulative_returns': benchmark_data['cumulative_returns'].tolist()
            })
    except Exception as e:
        print(f"加载沪深300数据失败: {e}")
    
    return None

def main():
    """主函数"""
    print("=" * 60)
    print("强势股策略回测分析")
    print("=" * 60)
    
    # 初始化回测引擎
    engine = CorrectBacktestEngine()
    engine.load_data()
    
    # 获取日期范围
    start_date = engine.screening_data['筛选日期'].min()
    end_date = engine.screening_data['筛选日期'].max()
    
    # 加载基准数据
    benchmark_df = load_cs300_benchmark(start_date, end_date)
    
    # 创建输出目录
    output_dir = Path("strong_backtest_results")
    output_dir.mkdir(exist_ok=True)
    
    # 运行不同策略
    strategies = {
        '1day': {'days': 1, 'name': '持有1天', 'color': 'red'},
        '2day': {'days': 2, 'name': '持有2天', 'color': 'blue'}, 
        '1week': {'days': 5, 'name': '持有1周', 'color': 'green'}
    }
    
    results = {}
    performance_metrics = []
    
    for strategy_key, strategy_info in strategies.items():
        result_df, trade_log = engine.run_backtest(strategy_info['days'])
        results[strategy_key] = result_df
        
        final_return = result_df['cumulative_returns'].iloc[-1] * 100
        final_value = result_df['total_value'].iloc[-1]
        print(f"{strategy_info['name']}策略:")
        print(f"  最终收益率: {final_return:.2f}%")
        print(f"  最终价值: {final_value:,.0f} 元")
        print()
        
        # 计算性能指标
        metrics = engine.calculate_performance_metrics(result_df, trade_log, strategy_info['name'])
        performance_metrics.append(metrics)
        
        # 保存详细交易记录到CSV文件
        engine.save_trade_log_to_csv(trade_log, strategy_key, output_dir)
    
    # 生成对比图
    if benchmark_df is not None:
        benchmark_return = benchmark_df['cumulative_returns'].iloc[-1] * 100
        print(f"沪深300基准收益率: {benchmark_return:.2f}%")
        print()
        
        # 单独对比图
        for strategy_key, strategy_info in strategies.items():
            if strategy_key in results:
                df = results[strategy_key]
                
                plt.figure(figsize=(12, 6))
                
                # 绘制基准
                plt.plot(benchmark_df['date'], benchmark_df['cumulative_returns'] * 100, 
                        label='沪深300基准', linewidth=2, alpha=0.8, color='gray')
                
                # 绘制策略
                plt.plot(df['date'], df['cumulative_returns'] * 100, 
                        label=f'{strategy_info["name"]}策略', linewidth=2, color=strategy_info['color'])
                
                plt.title(f'{strategy_info["name"]}策略 vs 沪深300基准 (手续费0.0086%)', 
                         fontsize=14, fontweight='bold')
                plt.xlabel('日期', fontsize=12)
                plt.ylabel('累计收益率 (%)', fontsize=12)
                plt.legend(fontsize=12)
                plt.grid(True, alpha=0.3)
                
                # 格式化x轴
                plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
                plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=1))
                plt.xticks(rotation=45)
                
                # 添加性能指标
                final_strategy_return = df['cumulative_returns'].iloc[-1] * 100
                excess_return = final_strategy_return - benchmark_return
                
                plt.text(0.02, 0.98, 
                        f'{strategy_info["name"]}: {final_strategy_return:.1f}%\n沪深300: {benchmark_return:.1f}%\n超额收益: {excess_return:+.1f}%',
                        transform=plt.gca().transAxes, fontsize=10, verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
                
                plt.tight_layout()
                plt.savefig(output_dir / f'{strategy_key}_vs_benchmark.png', dpi=300, bbox_inches='tight')
                plt.show()
                
                print(f"✅ 生成{strategy_info['name']}对比图")
        
        # 综合对比图
        plt.figure(figsize=(15, 8))
        
        plt.plot(benchmark_df['date'], benchmark_df['cumulative_returns'] * 100, 
                label='沪深300基准', linewidth=2, alpha=0.8, color='gray')
        
        for strategy_key, strategy_info in strategies.items():
            if strategy_key in results:
                df = results[strategy_key]
                plt.plot(df['date'], df['cumulative_returns'] * 100, 
                        label=f'{strategy_info["name"]}策略', linewidth=2, color=strategy_info['color'])
        
        plt.title('强势股策略累计收益率对比 (手续费0.0086%，滑点0.1%)', fontsize=16, fontweight='bold')
        plt.xlabel('日期', fontsize=12)
        plt.ylabel('累计收益率 (%)', fontsize=12)
        plt.legend(fontsize=12)
        plt.grid(True, alpha=0.3)
        
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        plt.savefig(output_dir / 'all_strategies_vs_benchmark.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        print("✅ 生成综合对比图")
    
    # 打印总结
    print("\n📋 强势股策略回测总结:")
    print("=" * 60)
    print("交易成本: 手续费0.0086%, 滑点0.1%")
    print("买卖方式: 开盘价买入, 收盘价卖出")
    print("调仓逻辑: 持有到期后清仓重新买入")
    print()
    
    if benchmark_df is not None:
        benchmark_return = benchmark_df['cumulative_returns'].iloc[-1] * 100
        print(f"沪深300基准收益率: {benchmark_return:.2f}%")
        
        for strategy_key, strategy_info in strategies.items():
            if strategy_key in results:
                df = results[strategy_key]
                strategy_return = df['cumulative_returns'].iloc[-1] * 100
                excess_return = strategy_return - benchmark_return
                final_value = df['total_value'].iloc[-1]
                print(f"{strategy_info['name']}策略: {strategy_return:.2f}% (超额收益: {excess_return:+.2f}%, 最终价值: {final_value:,.0f}元)")
    
    # 性能指标总结
    print("\n📊 策略性能指标:")
    print("=" * 60)
    print(f"{'策略':<10} {'总收益率':<10} {'日胜率':<8} {'夏普比率':<10} {'最大回撤':<10} {'交易次数':<8} {'交易胜率':<8}")
    print("-" * 60)
    
    for metrics in performance_metrics:
        print(f"{metrics['strategy']:<10} "
              f"{metrics['total_return']:>8.1f}% "
              f"{metrics['win_rate']:>6.1f}% "
              f"{metrics['sharpe_ratio']:>8.2f} "
              f"{metrics['max_drawdown']:>8.1f}% "
              f"{metrics['total_trades']:>6.0f} "
              f"{metrics['trade_win_rate']:>6.1f}%")
    
    print(f"\n✅ 图表已保存到: {output_dir}")

if __name__ == "__main__":
    main()