# S3 Free Tier Overage from Hourly Exports

**Date:** 2026-04-22
**Phase:** 4 — Cloud transformation (bronze → silver)
**Outcome:** Reduced export frequency from hourly to daily; identified transform script inefficiency for future optimization

---

## The problem

AWS billing showed S3 usage exceeding the free tier:
- **Tier 1 requests** (2,000/month free): at 2,000, forecasted 2,727
- **Tier 2 requests** (20,000/month free): at 7,301, forecasted 9,956

Root cause: `export_to_s3.py` was scheduled to run **every hour** via cron:
```bash
0 * * * * cd /home/travismagaluk/garagewatch && /usr/bin/python3 scripts/export_to_s3.py
```

## The math

Each `export_to_s3.py` run makes ~3–4 S3 API calls:
1. `get_watermark()` — 1 GET request
2. `write_to_s3()` — 1–2 PUT requests (depends on partitions; usually 1)
3. `update_watermark()` — 1 PUT request

**Hourly export:** 24 runs/day × 3–4 requests/run = **72–96 requests/day** = ~2,160–2,880/month

This was the entire Tier 1 overage.

## The fix

Changed cron to run once daily at midnight:
```bash
0 0 * * * cd /home/travismagaluk/garagewatch && /usr/bin/python3 scripts/export_to_s3.py
```

**New cost:** ~3–4 requests/day = ~90–120/month. **Well within free tier.**

Since the sensor collects 1 reading per 60 seconds, each hourly export was batching ~3,600 readings. A daily export batches ~86,400 readings — still a modest file, no loss of functionality.

---

## Phase 4.5 — Transform Script Optimization (Future)

**Note:** This optimization is not urgent (transform runs manually only), but when scaling or automating, fix the `transform_to_silver.py` script to avoid re-reading all bronze files on every run.

### Current inefficiency in `transform_to_silver.py`

Lines 101–102 re-read **every** bronze file for affected partitions on each run:

```python
for year, month in sorted(affected):
    bronze_keys = list_all_bronze_for_partition(s3, year, month)  # LIST request (paginated)
    frames = [read_csv_gz(s3, k) for k in bronze_keys]            # GET for EVERY file
    df = pd.concat(frames, ignore_index=True)
    # ... merge and write parquet
```

**Problem:** If a partition has N bronze files (e.g., 30 daily exports), every transform run re-downloads all N files to merge them. This generates N GET requests + paginated LIST requests unnecessarily.

### How to optimize (two approaches)

#### Approach 1: Only merge newly added bronze files (incremental merge)

Instead of re-reading all bronze files in a partition, only read the files added since the last silver parquet was written.

```python
def list_bronze_since(s3, year, month, after_key):
    """List bronze files in partition that are newer than after_key."""
    prefix = f"{BRONZE_PREFIX}year={year}/month={month}/"
    paginator = s3.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".csv.gz") and key > after_key:
                keys.append(key)
    return sorted(keys)

def main():
    s3 = boto3.client("s3")
    watermark = get_silver_watermark(s3)
    
    new_files = list_new_bronze_files(s3, watermark)
    if not new_files:
        return
    
    affected = set(partition_from_key(k) for k in new_files)
    
    for year, month in sorted(affected):
        # Key change: only read NEW bronze files, not all
        bronze_keys = list_bronze_since(s3, year, month, watermark)
        
        # Read existing silver parquet if it exists
        try:
            silver_key = f"{SILVER_PREFIX}year={year}/month={month}/readings_{year}{month}.parquet"
            existing_df = read_parquet(s3, silver_key)
        except s3.exceptions.NoSuchKey:
            existing_df = None
        
        # Read only the new bronze files
        frames = [read_csv_gz(s3, k) for k in bronze_keys]
        if existing_df is not None:
            frames.append(existing_df)
        
        df = (pd.concat(frames, ignore_index=True)
              .drop_duplicates(subset=["timestamp"])
              .sort_values("timestamp"))
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
        
        write_parquet(s3, df, year, month)
    
    # Update watermark
    s3.put_object(...)
```

**Cost:** Only N new bronze files are downloaded, not all files in the partition.

#### Approach 2: Track silver watermark per partition

Store the last processed bronze key **per partition**, not globally. This avoids re-processing old partitions entirely.

```python
def get_silver_watermark(s3, year, month):
    """Get watermark for a specific partition."""
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=f"silver_watermark_{year}_{month:02d}.json")
        return json.loads(obj["Body"].read())["last_key"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            return ""
        raise

def main():
    s3 = boto3.client("s3")
    watermark = get_silver_watermark(s3, None, None)  # Global watermark
    
    new_files = list_new_bronze_files(s3, watermark)
    if not new_files:
        return
    
    affected = set(partition_from_key(k) for k in new_files)
    
    for year, month in sorted(affected):
        # Per-partition watermark
        partition_watermark = get_silver_watermark(s3, year, month)
        
        # Only read bronze files newer than this partition's watermark
        bronze_keys = list_bronze_since(s3, year, month, partition_watermark)
        
        # ... rest of merge logic
        
        # Update per-partition watermark
        s3.put_object(
            Bucket=BUCKET,
            Key=f"silver_watermark_{year}_{month:02d}.json",
            Body=json.dumps({"last_key": bronze_keys[-1]}).encode()
        )
```

**Cost:** Each partition is processed only once. Zero re-reads of old bronze files.

### When to apply

- **Now (if running transforms frequently):** Use Approach 2 (per-partition watermark) for instant cost savings.
- **At scale:** Use Approach 1 (incremental merge) if re-reading the existing silver parquet becomes expensive.
- **If still manual:** Defer — the current script is fine for occasional runs.

---

## Lessons

- **Scheduling matters.** A reasonable-sounding cadence (hourly) compounds into expensive API call volume over a month. Calculate: `(requests per run) × (runs per day) × (days in month)`.
- **Free tier isn't free forever.** Monitor AWS cost anomalies early. The first overage is a great learning moment.
- **Partition-aware processing saves requests.** When transforming partitioned data (Hive style), watermark at the partition level, not globally, so you never re-process.
- **Incremental patterns beat full scans.** CSV merge scripts that re-read the entire partition on every run are a red flag. Use incremental merges or append-only silver layers (write once, never overwrite).

## References

- [AWS S3 Pricing — Free Tier](https://aws.amazon.com/s3/pricing/)
- [Linux cron job format](https://man7.org/linux/man-pages/man5/crontab.5.html)
- Medallion architecture best practice: source → bronze (raw) → silver (deduplicated, merged) → gold (business logic). Each layer should be processed once.
