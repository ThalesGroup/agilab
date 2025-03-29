from agi_core.workers.agi_worker import AgiWorker

args = {
    'data_source': "file",
    'path': "~/data/flight",
    'files': "csv/*",
    'nfile': 1,
    'nskip': 0,
    'nread': 0,
    'sampling_rate': 10.0,
    'datemin': "2020-01-01",
    'datemax': "2021-01-01",
    'output_format': "parquet"
}

# AgiWorker.run flight command
result = AgiWorker.run('flight', mode=0, verbose=3, args=args)
print(result)