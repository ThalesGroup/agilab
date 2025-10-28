import random
import logging, logging.handlers
from collections import defaultdict
import pandas as pd
import heapq
import numpy as np
import networkx as nx
from copy import deepcopy
from functools import partial
import pickle

#Gurobi solver
import gurobipy as gp
from gurobipy import GRB

class MILP():
    """
        ILP formulation of the bearer selection
        Use Gurobi solver in backend.
    """
    def __init__(self,env, logger):
        self.logger = logger
        #self.edges = env.edges
        self.edges = env.non_ordered_edges
        self.edges_index = env.edges
        self.env = env

    
    def solve(self, demands):
            """
            Solve bearer selection problem as an optimization problem.
                - constrain on available bandwidth per link (bearer)
                - constrain on maximum latency acceptable per flow. 
                - priority of flow management
                - 
            """
            with gp.Env(params=options) as env, gp.Model(env=env) as Model:
                m = gp.Model(env=env)
                
                #get the edges data.
                es = self.edges
                self.logger.debug(f"Environment Edges: {es}")
                
                nodes = self.env.nodes
                #get the nodes
                self.logger.debug(f"Environment nodes: {self.env.nodes}")
                                        
                self.logger.debug(f"Edges: {es}")

                for i, d in enumerate(demands):
                    self.logger.debug(f"Demands: {i} ")
                    self.logger.debug(f"Source demands: {d.source}")
                    self.logger.debug(f"Destination demands: {d.destination}")
                    self.logger.debug(f"Bw : {d.bw}")
                    self.logger.debug(f"maximum latency : {d.max_latency}")
                    self.logger.debug(f"min bw: {d.min_bw}")
                    self.logger.debug(f"Priority: {d.priority}")
                #self.logger.debug(f"Demands{[d for d in demands]}") 
                
                #number of flows
                self.logger.debug(f"Nb of flows: {len(demands)}")

                demand = defaultdict(int)
                source_node = dict()
                sink_node = dict()
                min_bw = dict()
                priority = dict()
                max_latency = dict()
                
                for i, f in enumerate(demands):
                    flow_id = 'f'+str(i)
                    demand.update({flow_id:f.bw})
                    source_node.update({flow_id:f.source})
                    sink_node.update({flow_id:f.destination})
                    min_bw.update({flow_id:f.min_bw})
                    priority.update({flow_id:f.priority})
                    max_latency.update({flow_id:f.max_latency})
                com = list(demand.keys())

                self.logger.debug(f"Loaded demand list: {demand}")
                self.logger.debug(f"Loaded demand src list: {source_node}")
                self.logger.debug(f"Loaded demand target list: {sink_node}")
                self.logger.debug(f"Flow list: {com}")

                #Variables
                flow = m.addVars(com, es, vtype=GRB.INTEGER,lb=0, name="flow")
                y = m.addVars(com, es, vtype=GRB.BINARY, name= "route")
 #               alpha = m.addVars(com, vtype=GRB.INTEGER, lb=0, name="unserved")
                phi = m.addVars(com, vtype=GRB.BINARY, name="routed")


                lat = []
                for i,j,k in es:
                    lat.append(self.env.graph_state[self.edges_index[str(i)+":"+str(j)+":"+str(k)]][2])
                print(f"{lat}")

                pl = m.addVars(com, es, vtype=GRB.INTEGER, name="paths_latency")
                
                self.logger.debug(f"flow: {flow}")
                #for (i, j, k), capacity in es.items():

                for s in self.env.graph_state:
                    print(s)

                paths_latency = defaultdict()
                
                for edge_index, state in enumerate(self.env.graph_state):
                    self.logger.debug(f"Capacity {state[0]}")
                    self.logger.debug(f"latency {state[2]}")
                    self.logger.debug(f"Bearer {state[3]}")
                    self.logger.debug(f"edge: {self.edges[edge_index]}")
                    
                    (i, j, k) = self.edges[edge_index]
                    capacity = state[0]
                    #paths_latency[(i,j,k)].update(state[2])
                    
                    m.addConstr(
                        gp.quicksum(flow[c, i, j, k] for c in com) <= capacity, name=f"cap_{i}_{j}_{k}"
                        )
                    for c in com:
                        m.addConstr(pl[c, i, j, k] == state[2], name="lat_{c}_{i}_{j}_{k}")
#                self.logger.debug("Paths latency {paths_latency.items()}")
                
                for c in com:
                    for (i,j,k) in es:
                        m.addConstr(flow[c, i, j, k] <= demand[c]*y[c, i, j, k], name=f"link_flow_usage_{c}_{i}_{j}_{k}")
                        

                #constrain for conservation of flow
                for c in com:
                    for node in nodes:
                        inflow = gp.quicksum(flow[c,i,j,k] for (i,j,k) in es if j == node)
                        outflow = gp.quicksum(flow[c,i,j,k] for (i,j,k) in es if i == node)

                        if node == source_node[c]:

                            m.addConstr(outflow - inflow >= min_bw[c]*phi[c], name=f"Min_bw_{c}")
                            m.addConstr(outflow - inflow <= demand[c]*phi[c] , name=f"flow_cons_{c}_{node}")
                            
                        elif node == sink_node[c]:
#                            m.addConstr(inflow - outflow == demand[c] - alpha[c], name=f"sink_flow_{c}_{node}")
                            m.addConstr(inflow - outflow >= min_bw[c]*phi[c], name=f"sink_flow_{c}_{node}")                            
                            m.addConstr(inflow - outflow <= demand[c]*phi[c], name=f"sink_flow_{c}_{node}")
                            
                            
                        else:
                            m.addConstr(inflow == outflow, name=f"flow_conservation_{c}_{node}")

                
                for c in com:
                    m.addConstr(
                            gp.quicksum(y[c, i, j, k] for (i, j, k) in es if i == source_node[c]) == phi[c], name=f"single_path_out{c}"
                        )

            
                #Additive constrain for max latency acceptance / flow.
                for c in com:
                    m.addConstr(
                            #gp.quicksum(self.env.graph_state[self.edges_index[str(i)+":"+str(j)+":"+str(k)]][2]*y[c,i,j,k] for (i,j,k) in es) <= max_latency[c]*phi[c], name=f"path_max_latency_{c}"
                            gp.quicksum(pl[c,i,j,k]*y[c,i,j,k] for (i,j,k) in es) <= max_latency[c]*phi[c], name=f"path_max_latency_{c}"
                        )
                    
                penalty_factor = 1000
#                t_flow = gp.quicksum(flow[c, i, j, k] for c in com for (i,j,k) in es) + penalty_factor *gp.quicksum(alpha[c] for c in com)
                t_flow = gp.quicksum(flow[c, i, j, k] for c in com for (i,j,k) in es) + penalty_factor * gp.quicksum((1-phi[c]) for c in com)
#                m.setObjective(t_flow, GRB.MAXIMIZE)
#                m.setObjective(t_flow, GRB.MINIMIZE)
                m.setObjective(gp.quicksum(phi[c]*(1/priority[c]) for c in com), GRB.MAXIMIZE)
                m.optimize()

                self.logger.debug(f"Total flow {GRB.OPTIMAL}")
                
                if m.status == GRB.OPTIMAL:
                    self.logger.debug(f"Total flow {m.objVal}")

                    for c in com:
                        self.logger.debug(f"flow {c} is {'routed' if phi[c].X > 0.5 else 'buffered or rejected'}")
                        path = []
                        for (i, j, k) in es:
#                            path_latency = pl[c, i, j, k].x
                            f = flow[c, i, j, k].x
#                            self.logger.debug(f"Latence on link {i}->{j}/{k} = {path_latency}")
                            if f > 1e-6:
#                                self.logger.debug(f"Commodity {c}: flow from {i} to {j} on edge {k} = {f}")
                                path.append([i,j,k,f])
                        self.logger.debug(f"Flow {c}: {demands[int(c[1])].source}->{demands[int(c[1])].destination}\
 is {'routed' if phi[c].X > 0.5 else 'admitted'} with path: {path}")




    
