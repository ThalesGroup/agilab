from scipy.signal import convolve2d as cv2
import numpy as np

# Define the window size for Savitzky-Golay filtering
window_size = 51

# Apply Savitzky-Golay filter to column 'long'
df['smoothed_long'] = cv2(df['long'].values, window_size, 2) / window_size