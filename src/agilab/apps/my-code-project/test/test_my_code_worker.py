from agi_core.workers.agi_worker import AgiWorker

args = {'param1': 0, 'param2': "some text", 'param3': 3.14, 'param4': True}

AgiWorker.run('my_code', mode=0, verbose=3, args=args)
# AgiWorker.run('my_code', mode=1, verbose=3, args=args)

# compilation cython and dask are managed by Agi so mode > 1 iare not available for unary test
# AgiWorker.run('my_code', mode=2, verbose=3, args=args)