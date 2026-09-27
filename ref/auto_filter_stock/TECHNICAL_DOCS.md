# 强势股回测系统技术文档

## 📋 系统概述

强势股回测系统是一个基于技术分析和动量策略的量化投资回测平台，通过分析股票的技术指标筛选出具有强势特征的股票组合，并进行多策略回测分析。

## 🏗️ 系统架构

### 核心组件

```
strong_backtest.py (主程序)
├── CorrectBacktestEngine (回测引擎)
│   ├── 数据加载模块
│   ├── 价格获取模块
│   ├── 交易执行模块
│   └── 结果输出模块
├── 策略配置
├── 基准数据加载
└── 可视化生成
```

### 数据流架构

```
数据输入 → 数据验证 → 策略执行 → 交易记录 → 结果输出
    ↓           ↓          ↓         ↓         ↓
筛选结果    交易日对齐   买入/卖出   详细日志   图表/CSV
交易数据    价格获取     持仓管理   交易统计   性能分析
基准数据    数据清洗     风险控制   成本计算   基准对比
```

## 🔧 核心算法

### 1. 数据加载与验证

```python
def load_data(self):
    """数据加载流程"""
    # 1. 加载筛选结果
    self.screening_data = pd.read_csv('data/daily_screening_results.csv')
    
    # 2. 加载交易数据
    self.trading_data = pd.read_stata('data/trading_data.dta')
    
    # 3. 数据预处理
    self.screening_data['筛选日期'] = pd.to_datetime(self.screening_data['筛选日期']).dt.date
    self.trading_data['Trddt'] = pd.to_datetime(self.trading_data['Trddt']).dt.date
    
    # 4. 交易日对齐检查
    self._validate_trading_day_alignment()
```

**关键特性**:
- 自动日期格式转换
- 交易日对齐验证
- 数据完整性检查

### 2. 价格获取算法

```python
def get_stock_price(self, stock_symbol, trade_date, price_type='close'):
    """价格获取核心算法"""
    try:
        # 1. 获取股票数据
        stock_data = self.trading_data.loc[stock_symbol, trade_date]
        
        # 2. 处理多行数据
        if isinstance(stock_data, pd.DataFrame):
            stock_data = stock_data.iloc[0]
        
        # 3. 价格类型选择
        if price_type == 'average':
            price = (stock_data['Hiprc'] + stock_data['Loprc']) / 2
        else:
            price = stock_data[price_type]
        
        # 4. 数据验证
        if pd.isna(price) or price <= 0:
            return 0
        
        return price
        
    except (KeyError, IndexError, TypeError, ValueError):
        return 0
```

**价格类型支持**:
- `open`: 开盘价
- `close`: 收盘价  
- `high`: 最高价
- `low`: 最低价
- `average`: 平均价 (最高价+最低价)/2

### 3. 交易执行逻辑

#### 买入逻辑

```python
# 买入条件判断
need_buy = False
if not current_positions:
    need_buy = True

if need_buy:
    # 1. 获取筛选结果
    screening_date = trading_dates[i - 1]  # T-1日筛选，T日买入
    daily_stocks = self.screening_data[
        self.screening_data['筛选日期'] == screening_date
    ]
    
    # 2. 价格验证
    valid_stocks = []
    for _, stock in daily_stocks.head(self.top_n).iterrows():
        open_price = self.get_stock_price(stock['股票代码'], trade_date, 'open')
        if open_price > 0:
            valid_stocks.append({
                'symbol': stock['股票代码'],
                'name': stock['股票名称'],
                'price': open_price * (1 + self.slippage_rate)  # 应用滑点
            })
    
    # 3. 等权重分配
    if valid_stocks:
        available_cash = current_cash
        stock_value = available_cash / len(valid_stocks)
        
        for stock_info in valid_stocks:
            quantity = int(stock_value / stock_info['price'])
            if quantity > 0:
                # 计算交易成本
                buy_amount = quantity * stock_info['price']
                commission = max(buy_amount * self.commission_rate, self.min_commission)
                total_cost = buy_amount + commission
                
                # 执行买入
                current_positions[stock_info['symbol']] = {
                    'name': stock_info['name'],
                    'quantity': quantity,
                    'buy_price': stock_info['price'],
                    'buy_date': trade_date
                }
```

#### 卖出逻辑

```python
# 卖出条件判断
for stock_symbol, position in list(current_positions.items()):
    buy_date = position['buy_date']
    buy_date_idx = date_to_index[buy_date]
    
    # 持有期判断：T日买入，T+holding_days日卖出
    if i - buy_date_idx == holding_days:
        # 获取卖出价格（平均价）
        average_price = self.get_stock_price(stock_symbol, trade_date, 'average')
        if average_price == 0:
            average_price = position['buy_price']  # 备用价格
        
        # 应用滑点
        actual_sell_price = average_price * (1 - self.slippage_rate)
        sell_amount = position['quantity'] * actual_sell_price
        commission = max(sell_amount * self.commission_rate, self.min_commission)
        net_amount = sell_amount - commission
        
        # 更新现金
        current_cash += net_amount
        
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
        
        # 移除持仓
        del current_positions[stock_symbol]
```

### 4. 策略配置

```python
strategies = {
    '1day': {'days': 1, 'name': '持有1天', 'color': 'red'},
    '2day': {'days': 2, 'name': '持有2天', 'color': 'blue'}, 
    '1week': {'days': 5, 'name': '持有1周', 'color': 'green'}
}
```

**策略特点**:
- **1天策略**: 每日调仓，捕捉短期动量
- **2天策略**: 隔日调仓，平衡频率与收益
- **1周策略**: 周度调仓，降低交易成本

### 5. 成本模型

```python
# 交易成本参数
commission_rate = 0.000086  # 手续费率 0.0086%
slippage_rate = 0.001      # 滑点率 0.1%
min_commission = 5         # 最小手续费 5元

# 买入成本计算
buy_amount = quantity * buy_price
commission = max(buy_amount * commission_rate, min_commission)
total_cost = buy_amount + commission

# 卖出成本计算
sell_amount = quantity * sell_price
commission = max(sell_amount * commission_rate, min_commission)
net_amount = sell_amount - commission
```

## 📊 数据模型

### 输入数据格式

#### 1. 筛选结果数据 (daily_screening_results.csv)
```csv
筛选日期,股票代码,股票名称,其他字段...
2025-01-02,000001.SZ,平安银行,...
2025-01-02,000002.SZ,万科A,...
```

#### 2. 交易数据 (trading_data.dta)
```stata
Stkcd    Trddt      Opnprc   Hiprc    Loprc    Clsprc
000001   2025-01-02  10.50    10.80    10.30    10.70
000001   2025-01-03  10.70    11.00    10.60    10.90
```

#### 3. 基准数据 (CS300.dta)
```stata
Trddt      Clsprc
2025-01-02  3500.50
2025-01-03  3520.30
```

### 输出数据格式

#### 1. 交易记录 (详细交易记录.csv)
```csv
日期,天数,操作类型,股票代码,股票名称,数量,价格,金额,手续费,净收入,现金余额,持仓价值,总价值
2025-01-02,1,买入,000001.SZ,平安银行,1000,10.50,10500,5.0,-10505,95000,10500,100000
2025-01-03,2,卖出,000001.SZ,平安银行,1000,10.70,10700,5.0,10695,105695,0,105695
```

#### 2. 回测结果数据
```python
returns_data = {
    'date': [日期列表],
    'total_value': [总价值列表],
    'cumulative_returns': [累计收益率列表]
}
```

## 🔄 执行流程

### 主回测流程

```python
def run_backtest(self, holding_days):
    """回测主流程"""
    # 1. 初始化
    current_cash = self.initial_capital
    current_positions = {}
    returns_data = []
    trade_log = []
    
    # 2. 遍历交易日
    for i, trade_date in enumerate(trading_dates):
        # 2.1 卖出逻辑
        sold_stocks = []
        for stock_symbol, position in list(current_positions.items()):
            if should_sell(position, trade_date, holding_days):
                sell_stock(stock_symbol, position, trade_date)
        
        # 2.2 买入逻辑
        bought_stocks = []
        if need_to_buy(current_positions):
            buy_stocks(trade_date)
        
        # 2.3 更新持仓价值
        update_portfolio_value()
        
        # 2.4 记录交易日志
        log_daily_trades()
        
        # 2.5 计算收益率
        calculate_returns()
    
    return results_df, trade_log
```

### 关键决策点

1. **买入时机**: 无持仓时立即买入
2. **卖出时机**: 持有期满时卖出
3. **调仓频率**: 根据策略类型决定
4. **价格选择**: 买入用开盘价，卖出用平均价

## 📈 性能指标

### 计算指标

```python
# 累计收益率
cumulative_return = (total_value - initial_capital) / initial_capital

# 超额收益
excess_return = strategy_return - benchmark_return

# 夏普比率 (简化)
sharpe_ratio = excess_return / volatility
```

### 输出指标

- **最终收益率**: 策略总收益
- **超额收益**: 相对基准的超额表现
- **最大回撤**: 最大资产回撤
- **交易次数**: 买入/卖出次数统计

## 🎨 可视化系统

### 图表生成

```python
def generate_charts(results, benchmark_df, output_dir):
    """图表生成流程"""
    # 1. 单策略对比图
    for strategy_key, result_df in results.items():
        create_strategy_chart(result_df, benchmark_df)
    
    # 2. 综合对比图
    create_comprehensive_chart(results, benchmark_df)
```

### 图表类型

1. **累计收益率曲线**: 策略vs基准
2. **超额收益曲线**: 策略相对基准表现
3. **综合对比图**: 多策略同时对比

## 🔍 数据验证

### 输入验证

```python
def _validate_trading_day_alignment(self):
    """交易日对齐检查"""
    screening_dates = set(self.screening_data['筛选日期'])
    trading_dates = set(self.trading_data['Trddt'])
    
    missing_in_screening = trading_dates - screening_dates
    if missing_in_screening:
        print(f"ℹ️  信息: 发现{len(missing_in_screening)}个交易日期不在筛选数据中")
```

### 价格验证

```python
def get_stock_price(self, stock_symbol, trade_date, price_type='close'):
    """价格获取与验证"""
    try:
        # 数据获取
        stock_data = self.trading_data.loc[stock_symbol, trade_date]
        
        # 数据清洗
        if isinstance(stock_data, pd.DataFrame):
            stock_data = stock_data.iloc[0]
        
        # 价格计算
        price = calculate_price(stock_data, price_type)
        
        # 数据验证
        if pd.isna(price) or price <= 0:
            return 0
        
        return price
        
    except (KeyError, IndexError, TypeError, ValueError):
        return 0
```

## ⚙️ 配置参数

### 交易参数

```python
# 资金配置
initial_capital = 1000000  # 初始资金 100万
top_n = 10                # 每次买入股票数量

# 成本参数
commission_rate = 0.000086  # 手续费率
slippage_rate = 0.001       # 滑点率
min_commission = 5          # 最小手续费

# 策略参数
strategies = {
    '1day': {'days': 1, 'name': '持有1天'},
    '2day': {'days': 2, 'name': '持有2天'}, 
    '1week': {'days': 5, 'name': '持有1周'}
}
```

### 输出配置

```python
# 输出目录
output_dir = Path("strong_backtest_results")

# 图表配置
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
```

## 🚨 异常处理

### 数据异常

```python
# 价格数据异常
if pd.isna(price) or price <= 0:
    return 0  # 返回0表示数据无效

# 股票代码异常
try:
    stock_data = self.trading_data.loc[stock_symbol, trade_date]
except KeyError:
    return 0  # 股票不存在
```

### 交易异常

```python
# 资金不足
if total_cost > current_cash:
    continue  # 跳过该股票

# 数量为0
if quantity <= 0:
    continue  # 跳过该股票
```

## 📝 日志系统

### 交易日志

```python
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
```

### 进度显示

```python
if i % 20 == 0:
    print(f"  处理进度: {i+1}/{total_days}")
    if need_buy:
        print(f"    {trade_date}: 需要买入新股票")
    else:
        print(f"    {trade_date}: 有持仓，不买入")
```

## 🔧 扩展接口

### 自定义策略

```python
def add_custom_strategy(days, name, color):
    """添加自定义策略"""
    strategies[f'custom_{days}'] = {
        'days': days, 
        'name': name, 
        'color': color
    }
```

### 自定义成本模型

```python
def set_custom_costs(commission, slippage, min_comm):
    """设置自定义成本参数"""
    self.commission_rate = commission
    self.slippage_rate = slippage
    self.min_commission = min_comm
```

## 📊 性能优化

### 数据索引优化

```python
# 使用多级索引提高查询效率
self.trading_data.set_index(['Stkcd', 'Trddt'], inplace=True)

# 创建日期索引映射
date_to_index = {date: i for i, date in enumerate(trading_dates)}
```

### 内存优化

```python
# 分批处理大数据
chunk_size = 1000
for chunk in pd.read_csv('large_file.csv', chunksize=chunk_size):
    process_chunk(chunk)
```

## 🎯 最佳实践

### 代码组织

1. **模块化设计**: 功能分离，便于维护
2. **参数配置**: 集中管理配置参数
3. **异常处理**: 完善的错误处理机制
4. **日志记录**: 详细的运行日志

### 数据处理

1. **数据验证**: 输入数据完整性检查
2. **格式统一**: 统一的数据格式标准
3. **性能优化**: 高效的数据处理算法

### 结果输出

1. **多格式输出**: CSV + 图表
2. **详细记录**: 完整的交易记录
3. **可视化**: 直观的图表展示

---

**技术文档版本**: v1.0  
**最后更新**: 2025-10-21  
**维护者**: 强势股回测系统开发团队



