def merge_intervals(intervals):
    if not intervals:
        return []

    # Sort intervals by their start value
    intervals.sort(key=lambda x: x[0])

    merged = [intervals[0]]
    for current in intervals[1:]:
        last_merged = merged[-1]
        if current[0] <= last_merged[1]:
            # Merge overlapping intervals
            merged[-1] = (last_merged[0], max(last_merged[1], current[1]))
        else:
            # Add non-overlapping interval
            merged.append(current)

    return merged