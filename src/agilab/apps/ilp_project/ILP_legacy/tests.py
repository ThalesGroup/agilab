from ga import *
from ea import *
from milp import *
from flyenv import *
from demand import Demand
import random
from deap import base, creator, tools, algorithms
from collections import defaultdict
import pandas as pd
import heapq
import numpy as np

import unittest
from unittest.mock import MagicMock, Mock, patch, ANY, call
import logging, logging.handlers


def mock_demands():
    demands = defaultdict[list]
    first_demand = demand(0,1,100,1)
    second_demand = demand(2,3,100,10)
    demands.append(first_demands)
    demands.append(second_demands)
    
class Test(unittest.TestCase):
    """Tests for the main class GA"""
    def setUp(self):
        self.logger = logging.getLogger('TEST')
        self.logger.setLevel(logging.DEBUG)
        #fh = logging.handlers.RotatingFileHandler('./test_ga.log', maxBytes=10000, backupCount=20)
        #fh.setLevel(logging.DEBUG)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        format_debug_logger = logging.Formatter('%(asctime)s %(filename)s %(name)s - %(funcName)s - %(levelname)s - %(message)s')
        format_logger = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        #fh.setFormatter(format_logger)
        console_handler.setFormatter(format_debug_logger)
        #add handlers to the logger
        #self.logger.addHandler(fh)
        self.logger.addHandler(console_handler)
    
    def tearDown(self):
        self.logger.handlers.pop()
        gc.collect()
	
    def test_demand_generation(self):
        env= Flyenv()
        _, _, demands = env.generate_connectivity_demand(1)
        #self.assertEqual(len(demands),1)
        print(f"Generated demands:\n{demands} ")

    def test_MILP_solve_3NP(self):
        env = Flyenv()
        env.reset()
        demands = [Demand(0,1,7000,2,10,100),Demand(0,2,500,1,0,800),Demand(2,1,8000,1,10,200),Demand(2,1,4000,1,10,200)]
        #Initialisze with 3N topology.
        env.generate_environment('topo3N', demands)
        #dm, list_demands, demands = env.generate_connectivity_demand(20)
        #Src|Dst|Bw|prority|Max_latency
        self.logger.debug(f"Generated demands: {demands}")
        model = MILP(env, self.logger)
        model.solve(demands)

        
    def test_solve_3ND(self):
        '''
            Python lib come with test license limiting instance size to about 100 demand and 40 nodes.
        '''
        env = Flyenv()
        env.reset()
        nb_demand = 20 #Number of demands for each nodes.
        #Initialisze with 3N topology.
        
        dm, list_demands, demands = env.generate_connectivity_demand(nb_demand)
        self.logger.debug(f"Generated demands: {demands}")

        for i, d in enumerate(list_demands):
            print(f"demand {i}:{d.source}")

        env.generate_environment('topo3N', list_demands)
        model = MILP(env, self.logger)
        model.solve(list_demands)

 
if __name__ == '__main__':
    unittest.main(verbosity=2,exit=False)
