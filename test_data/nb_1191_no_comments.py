import pandas as pd
import numpy as np
from pathlib import Path
from sklearn.linear_model import LinearRegression
df = pd.read_csv(
    Path("../Resources/oil_futures.csv"), parse_dates=True, index_col="Date"
)

df.head()
df.Settle.plot()
returns = df.Settle.pct_change() * 100
returns.plot()
df['Return'] = returns.copy()
df['Lag_Return'] = returns.shift()
df = df.dropna()
df.head()
y = df.Return
x = df.Lag_Return.to_frame()
x.head()
x['week_of_year'] = x.index.weekofyear
x.head()
X_binary_encoded = pd.get_dummies(x, columns=['week_of_year'])
X_binary_encoded.head()
X_binary_encoded.shape

from sklearn.metrics import mean_squared_error, r2_score

print(f"R-squared (R2 ): {r2}")
print(f"Mean Squared Error (MSE): {mse}")
print(f"Root Mean Squared Error (RMSE): {rmse}")
print(f"Standard Deviation of Futures Return: {np.std(y)}")
