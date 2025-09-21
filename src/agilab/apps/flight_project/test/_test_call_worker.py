from agi_node.agi_dispatcher import  BaseWorker
import asyncio

async def main():
  BaseWorker._new(active_app="flight_worker", mode=0, verbose=True, args={'data_source': 'file', 'data_uri': 'data/flight/dataset', 'files': 'csv/*', 'nfile': 2, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'csv'})
  res = await BaseWorker._run(workers={'127.0.0.1': 1}, mode=0, args={'data_source': 'file', 'data_uri': 'data/flight/dataset', 'files': 'csv/*', 'nfile': 2, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'csv'})
  print(res)

if __name__ == '__main__':
    asyncio.run(main())