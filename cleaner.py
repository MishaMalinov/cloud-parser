import pandas as pd

# Read CSV (auto-detect delimiter and encoding if needed)
df = pd.read_csv("all_products.csv")

# Drop columns that are completely empty (all NaN)
df = df.dropna(axis=1, how="all")

# Also drop columns that are empty strings only
df = df.loc[:, (df.astype(str).ne("")).any(axis=0)]

# Save cleaned CSV
df.to_csv("cleaned_products.csv", index=False, encoding="utf-8-sig")

print("✅ Cleaned CSV saved as 'cleaned.csv'")
