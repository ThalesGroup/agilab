from collections import defaultdict
from pathlib import Path
from itertools import islice
from importlib import resources
import gc
import random

try:  # pragma: no cover - optional dependency
    import gymnasium as gym
except ModuleNotFoundError:  # pragma: no cover - fallback for lightweight installs
    class _DummyEnv:  # type: ignore[override]
        pass

    class gym:  # type: ignore[override]
        Env = _DummyEnv

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np


from ilp_worker.demand import Demand

DEFAULT_TOPOLOGY = "topo3N"

def draw_edges(g, pos, ax):
    connectionstyle= [f"arc3,rad={r}" for r in np.abs(np.random.randn(20))*1.e-1+0.05]
    for i, e in enumerate(g.edges):
        ax.annotate("",
                    xy = pos[e[1]],
                    xycoords='data',
                    xytext = pos[e[0]], 
                    textcoords='data',
                    arrowprops = dict(arrowstyle="->", 
                                      color="k",
                                      shrinkA=15,
                                      shrinkB=15,
                                      patchA=None,
                                      patchB=None,
                                      connectionstyle = connectionstyle[i]
                                     )
                   )   
        nx.draw_networkx_edge_labels(g,pos,label_pos=0.3,font_color="blue",bbox={"alpha": 0},connectionstyle=connectionstyle)
    
        
def draw_nodes(g, pos, nodes, type = 'ngf'):
    colors = {"ngf":"lightcoral","hrc":"lightblue","lrc":"lightgrey"}
    shapes ={"ngf":'^',"hrc":'h',"lrc":'o' }
    nx.draw_networkx_nodes(g, pos,nodelist = nodes, node_color = colors[type] ,node_shape=shapes[type],edgecolors='black', node_size = 800, alpha = 0.7)
    nx.draw_networkx_labels(g,pos,font_size=8,font_color='k')

def get_type_node(G):
    nngf=[]
    nhrc=[]
    nlrc=[]
    ihrc=ingf=ilrc=0
    for n in G.nodes():
        if nx.get_node_attributes(G, 'type')[n]=='ngf':
            nngf.append(n)
            ingf += 1
        elif nx.get_node_attributes(G, 'type')[n]=='hrc':
            nhrc.append(n)
            ihrc += 1
        else:
            nlrc.append(n)
            ilrc += 1
    return nngf,nhrc,nlrc


def display_graph(g):
    print(g.edges())
    pos = nx.shell_layout(g)    
    node_types = nx.get_node_attributes(g, 'type')
    #nc = [colors[t]for t in node_types.values()]
    #ns = [shapes[t]for t in node_types.values()]
    plt.figure(figsize=(15,8))
    ngf_nodes, hrc_nodes, lrc_nodes = get_type_node(g)
    ax = plt.gca()
    draw_nodes(g,pos,ngf_nodes,'ngf')
    draw_nodes(g,pos,hrc_nodes,'hrc')
    draw_nodes(g,pos,lrc_nodes,'lrc')
    draw_edges(g,pos,ax)
    #plt.axis('off')
    plt.show()

def create_mesh4():
    Gbase = nx.MultiDiGraph()
    Gbase.add_nodes_from([0, 1, 2, 3])
    Gbase.add_edges_from(
        [(0, 1, 0),(0, 1, 0), (0, 2), (0, 3), (1, 0), (1, 2), (1, 3), (2, 0), (2, 1), (2, 3), (3, 0), (3, 1), (3, 2)])
    return Gbase

def create_4_nodes_swarm():
    path_name = "topo4N.txt"
    G = nx.read_gml(path_name, destringizer=int)
    return G

def create_3NP():
    print("!!! loading 3Nodes swarm")
    try:
        data_file = resources.files("ilp_worker").joinpath("data/topo3N.txt")
        with resources.as_file(data_file) as path_name:
            G = nx.read_gml(path_name, destringizer=int)
            return G
    except (FileNotFoundError, ModuleNotFoundError):  # pragma: no cover - runtime fallback
        base_dir = Path(__file__).resolve().parent
        legacy_path = base_dir.parent / "data" / "topo3N.txt"
        if not legacy_path.exists():
            raise FileNotFoundError(
                "topo3N.txt not found in packaged resources or legacy data directory"
            ) from None
        G = nx.read_gml(legacy_path, destringizer=int)
        return G
    
def generate_nx_graph(topology):
    """Generate graphs for training with the same topology."""

    if topology == 'topo3N':
        graph = create_3NP()
    elif topology == 3:
        graph = create_4_nodes_swarm()
        nx.set_edge_attributes(graph, 0, 'latency')
    elif topology == 4:
        graph = create_mesh4()
        nx.set_edge_attributes(graph, 0, 'latency')
    else:
        raise ValueError(f"Unsupported topology '{topology}'.")

    # Node id counter
    Id = 1
    for s, d, k in graph.edges(keys=True):
        graph.get_edge_data(s, d)[k]['id'] = Id
        graph.get_edge_data(s, d)[k]['bw_allocated'] = 0
        Id += 1

    nx.set_edge_attributes(graph, 0, 'betweenness')
    nx.set_edge_attributes(graph, 0, 'nb_sp')
    gc.collect()
    return graph


def compute_link_betweenness(g, k):
    n = len(g.nodes())
    betw = []
    for i, j in g.edges():
        # we add a very small number to avoid division by zero
        b_link = g.get_edge_data(i, j)['nb_sp'] / ((2.0 * n * (n - 1) * k) + 0.00000001)
        g.get_edge_data(i, j)['betweenness'] = b_link
        betw.append(b_link)

    mu_bet = np.mean(betw)
    std_bet = np.std(betw)
    return mu_bet, std_bet


BEARER = 3
CAPACITY = 0
DEMAND_DEFAULT = [100, 1000, 400]
bearer = {'sat':1,'ivdl':2,'opt':3}
NUM_PRIORITY = 5

class Flyenv(gym.Env):
    """
    Description:
    The self.graph_state stores the relevant features for the GNN model

    self.graph_state[:][0] = CAPACITY
    self.graph_state[:][1] = BW_ALLOCATED
  """
    def __init__(self):
        self.graph = None
        self.initial_state = None
        self.source = None
        self.destination = None
        self.demand = None
        self.graph_state = None
        self.diameter = None

        # Nx Graph where the nodes have features. Betweenness is allways normalized.
        # The other features are "raw" and are being normalized before prediction
        self.first = None
        self.firstTrueSize = None
        self.second = None
        self.between_feature = None

        # Mean and standard deviation of link betweenness
        self.mu_bet = None
        self.std_bet = None

        self.max_demand = 0
        self.K = 4
        self.demands = None
        self.nodes = None
        self.ordered_edges = None

        
#        self.edges_dict = None
        self.edges = None
        self.num_nodes = None
        self.num_edges = None

        self.state = None
        self.episode_over = True
        self.reward = 0
        self.paths = dict()

        #generate the environment
        self.demands = [100, 1000, 400]
        self.generate_environment(DEFAULT_TOPOLOGY, self.demands)

    def seed(self, seed):
        random.seed(seed)
        np.random.seed(seed)

    def shortest_path(self):
        """
        compute shortest path between all the graph nodes.
        select a subset with nb of sp selected defined by constant K
    
        """
        nb_max_sp = 4
        maximum_eccentricity = nx.diameter(self.graph)
        
        for src in self.graph.nodes():
            for dst in self.graph.nodes(): 
                if src != dst:
                    #generate the simple path with no loop aka repetetion of nodes.
                    shortest_paths = [path for path in nx.all_simple_paths(self.graph,src,dst, cutoff=maximum_eccentricity)]
                    shortest_paths = sorted(shortest_paths, key = lambda p: len(p))
                    self.paths.update({str(src)+":"+str(dst): [p for _, p in enumerate(islice(shortest_paths, nb_max_sp))]})
                    
                    path = self.paths[str(src)+":"+str(dst)]
                    for n_link in range(len(path)):
                        current_edge = path[n_link]
                        #update all the parallel edges for this particular segment of the path:
                        nb_edge = len(self.graph.get_edge_data(current_edge[0],current_edge[1]))
                        for e in range(nb_edge):
                            link_nb_sp = self.graph.get_edge_data(current_edge[0],current_edge[1])[e]['nb_sp']
                            self.graph.get_edge_data(current_edge[0],current_edge[1])[e]['nb_sp'] = link_nb_sp + 1
                                
        gc.collect()

    def _first_second_between(self):
        self.first = list()
        self.second = list()

        # For each edge we iterate over all neighbour edges
        for i, j in self.ordered_edges:
            neighbour_edges = self.graph.edges(i)

            for m, n in neighbour_edges:
                if ((i != m or j != n) and (i != n or j != m)):
                    self.first.append(self.edgesDict[str(i) +':'+ str(j)])
                    self.second.append(self.edgesDict[str(m) +':'+ str(n)])

            neighbour_edges = self.graph.edges(j)
            for m, n in neighbour_edges:
                if ((i != m or j != n) and (i != n or j != m)):
                    self.first.append(self.edgesDict[str(i) +':'+ str(j)])
                    self.second.append(self.edgesDict[str(m) +':'+ str(n)])

    def generate_environment(self, topology, listofdemands):
        # The nx graph will only be used to convert graph from edges to nodes
        self.graph = generate_nx_graph(topology)
        self.nodes = list(self.graph.nodes)
        self.listofDemands = listofdemands

#        self.max_demand = np.amax(self.listofDemands)
        
        # Compute number of shortest paths per link. This will be used for the betweenness
        self.shortest_path()

        # Compute the betweenness value for each link
 ##       self.mu_bet, self.std_bet = compute_link_betweenness(self.graph, self.K)

        self.edges = dict()

        #some_edges_1 = [tuple(sorted(edge)) for edge in self.graph.edges()]
        #self.ordered_edges = sorted(some_edges_1)
        self.non_ordered_edges = [e for e in self.graph.edges(keys=True)]
        self.ordered_edges = sorted([tuple(sorted(e[:2]))+(e[2],) for e in self.graph.edges(keys=True)])
        
        self.num_nodes = self.graph.number_of_nodes()
        self.num_edges = self.graph.number_of_edges()

        self.graph_state = np.zeros((self.num_edges, 5))
        #self.between_feature = np.zeros(self.nb_edges)
        self.edges_betweenness = np.zeros(self.num_edges)

        print(f"Ordered edges {self.ordered_edges}")
        for i,edge in enumerate(self.non_ordered_edges):
            print(f"{str(edge[0])}:{str(edge[1])}:{str(edge[2])}")
            self.edges[str(edge[0])+":"+str(edge[1])+":"+str(edge[2])] = i
            #self.edges[str(edge[1])+":"+str(edge[0])+":"+str(edge[2])] = i

            self.graph_state[i][CAPACITY] = self.graph.get_edge_data(edge[0], edge[1])[edge[2]]["capacity"]
            print(f"Current capacity of the edge: {self.graph.get_edge_data(edge[0], edge[1])[edge[2]]['capacity']}")
            self.graph_state[i][2] = self.graph.get_edge_data(edge[0], edge[1])[edge[2]]["latency"]
            self.graph_state[i][3] = edge[2] # Index for multi-graph
            self.graph_state[i][4] = bearer[self.graph.get_edge_data(edge[0], edge[1])[edge[2]]["bearer"].lower()]#record type bearer used.
            
        self.initial_state = np.copy(self.graph_state)

    def step(self, state, action, source, destination, demand):
        """
            Apply to the chosen action to the environment and return the new state and reward.
        """
        self.graph_state = np.copy(state)
        self.episode_over = True
        self.reward = 0
        print(f"edges: {self.edges}")
        i = 0
        j = 1

        #
#        print(f"src:{source}-destination:{destination}")
        currentPath = self.paths[str(source) +':'+ str(destination)][action]

        # Once we pick the action, we decrease the total edge capacity from the edges
        # from the allocated path (action path)
        while (j < len(currentPath)):
#            self.graph_state[self.edgesDict[str(currentPath[i]) + ':' + str(currentPath[j])]][0] -= demand
#            if self.graph_state[self.edgesDict[str(currentPath[i]) + ':' + str(currentPath[j])]][0] < 0:
            self.graph_state[self.edges[str(currentPath[i]) + ':' + str(currentPath[j])]][0] -= demand
            if self.graph_state[self.edges[str(currentPath[i]) + ':' + str(currentPath[j])]][0] < 0:

                
                # FINISH IF LINKS CAPACITY <0
                return self.graph_state, self.reward, self.episode_over, self.demand, self.source, self.destination 
            i = i + 1
            j = j + 1

        # Leave the bw_allocated back to 0
        self.graph_state[:,1] = 0

        # Reward is the allocated demand or 0 otherwise (end of episode)
        # We normalize the demand to don't have extremely large values
        self.reward = demand/self.max_demand
        self.episode_over = False

        self.demand = random.choice(self.listofDemands)
        self.source = random.choice(self.nodes)

        # We pick a pair of SOURCE,DESTINATION different nodes
        while True:
            self.destination = random.choice(self.nodes)
            if self.destination != self.source:
                break

        return self.graph_state, self.reward, self.episode_over, self.demand, self.source, self.destination

    def reset(self):
        """
        Reset environment and setup for new episode. Generate new demand and pair source, destination.

        Returns:
            initial state of the environment, a new demand and a source and destination node
        """
        self.graph_state = np.copy(self.initial_state)
        self.demand = random.choice(self.listofDemands)
        #self.source = random.choice(self.nodes)
        self.source = random.randint(0,self.num_nodes-1)
        print(f"reset state")
        # We pick a pair of SOURCE,DESTINATION different nodes
        while True:
            #self.destination = random.choice(self.nodes)
            self.destination = random.randint(0,self.num_nodes-1)
            print(f"dest:{self.destination}")
            if self.destination != self.source:
                break

        return self.graph_state, self.demand, self.source, self.destination
    
    def eval_sap_reset(self, demand, source, destination):
        """
        Reset environment and setup for new episode. This function is used in the "evaluate_DQN.py" script.
        """
        self.graph_state = np.copy(self.initial_state)
        self.demand = demand
        self.source = source
        self.destination = destination

        return self.graph_state

    def render(self):
        """
        Display the the current state of the environment. 
        * print the graph using networkX 
        * potential additionnal data related to plane context
            + position
            + speed 
            + ...
        """
        pos = nx.shell_layout(self.graph)    
        node_types = nx.get_node_attributes(self.graph, 'type')
        plt.figure(figsize=(6,4))
        ngf_nodes, hrc_nodes, lrc_nodes = get_type_node(self.graph)
        ax = plt.gca()
        draw_nodes(self.graph,pos,ngf_nodes,'ngf')
        draw_nodes(self.graph,pos,hrc_nodes,'hrc')
        draw_nodes(self.graph,pos,lrc_nodes,'lrc')
        draw_edges(self.graph,pos,ax)
        plt.axis('off')
        plt.show()

    def load_traffic_matrix(self):
        """
            use to load a traffic matrix from .txt
        """
        
    def generate_connectivity_demand(self, num_demands):
        """
            Generate a traffic matrix for a defined winwdow or horizon.
        """
        MAX_CAPA_SAT = 50000
        MAX_CAPACITY_IVDL = 10000
        MAX_CAPACITY_LOSS = 100000
        NB_MAX_DEMANDS = 20 #maximum number of flow

        demand_matrix = np.zeros((self.num_nodes,self.num_nodes))
        demands =[]
        upper_cap_demand = int(np.max([MAX_CAPA_SAT, MAX_CAPACITY_IVDL, MAX_CAPACITY_LOSS])/NB_MAX_DEMANDS)
        lower_cap_demand = int(upper_cap_demand/1000)
        #demands per source-destination
        demands_src_dst = defaultdict(list) 
        for src in range(self.num_nodes):
            #num_demands = random.randint(0, NB_MAX_DEMANDS)
            
            for i in range(num_demands):
                #select target nodes
                while True:
                    dst = random.randint(0,self.num_nodes-1)
                    if dst != src:
                        break
                bw_demand = random.randint(lower_cap_demand, upper_cap_demand)
                priority = random.randint(1, NUM_PRIORITY)
                demand_matrix[src, dst] += bw_demand
                demands_src_dst[str(src)+':'+str(dst)].append(bw_demand)
                demands.append(Demand(src,dst,bw_demand,priority))
                    
        print(f"Demand matrix \n {demand_matrix}")
        print(f"demands \n {demands}")
        print(f"graph state: {self.graph_state}")
        
        return demand_matrix, demands, demands_src_dst
