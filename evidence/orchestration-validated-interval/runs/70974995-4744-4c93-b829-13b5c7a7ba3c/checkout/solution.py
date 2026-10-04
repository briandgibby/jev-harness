def merge_intervals(intervals):
    ordered = sorted(intervals)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            left, right = merged[-1]
            merged[-1] = (left, max(right, end))
        else:
            merged.append((start, end))
    return merged
