from agi_node.agi_dispatcher import  BaseWorker
import asyncio
async def main():
  BaseWorker.new(mode=0, install_type=1, verbose=True, args={'data_source': 'file', 'path': 'data/flight/dataset', 'files': 'csv/*', 'nfile': 2, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'csv'})
  res = await BaseWorker.run(env=None, workers={'127.0.0.1': 1}, mode=0, verbose=True, args={'data_source': 'file', 'path': 'data/flight/dataset', 'files': 'csv/*', 'nfile': 2, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'csv'})
  print(res)
if __name__ == '__main__':
  try:
      asyncio.get_running_loop().run_until_complete(main())
  except RuntimeError:
      asyncio.run(main())