from scipy.signal import savgol_filter

# Apply Savitzky-Golay filter to smooth 'long' column
df['long_smoothed'] = savgol_filter(df['long'], window_length=5, polyorder=2)