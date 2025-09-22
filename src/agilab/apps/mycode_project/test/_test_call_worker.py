from agi_node.agi_dispatcher import  BaseWorker
import asyncio

async def main():
  BaseWorker._new(active_app="mycode_worker", mode=0, verbose=True, args={'param1': 0, 'param2': 'some text', 'param3': 3.14, 'param4': True})
  res = await BaseWorker._run(workers={'127.0.0.1': 2}, mode=0, args={'param1': 0, 'param2': 'some text', 'param3': 3.14, 'param4': True})
  print(res)

if __name__ == '__main__':
  asyncio.run(main())