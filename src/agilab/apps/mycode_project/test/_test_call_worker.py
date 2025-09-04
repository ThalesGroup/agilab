from agi_node.agi_dispatcher import  BaseWorker
import asyncio

async def main():
  BaseWorker.new(mode=0, install_type=1, verbose=True, args={'param1': 0, 'param2': 'some text', 'param3': 3.14, 'param4': True})
  res = await BaseWorker.run(env=None, workers={'127.0.0.1': 2}, mode=0, verbose=True, args={'param1': 0, 'param2': 'some text', 'param3': 3.14, 'param4': True})
  print(res)

if __name__ == '__main__':
  asyncio.run(main())