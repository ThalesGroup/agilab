from scipy.signal import savgol_filter

df['smoothed_long'] = savgol_filter(df['long'], window_length=5, polyorder=2)