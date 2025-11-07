from agi_node.agi_dispatcher import  BaseWorker
import asyncio

async def main():
  args = {'data_source': 'file', 'data_in': 'data/flight/dataset', 'data_out': 'data/flight/dataframe',
          'files': 'csv/*', 'nfile': 2, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0,
          'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'csv'}
  BaseWorker._new(active_app="flight_worker", mode=0, verbose=True, args=args)
  res = await BaseWorker._run(workers={'127.0.0.1': 1}, mode=0, args=args)
  print(res)

if __name__ == '__main__':
    asyncio.run(main())
