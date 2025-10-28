from copy import deepcopy

class Demand():
    """
        class to model a demand between plateform
    """
    def __init__(self,source,destination,bw,priority=1,max_packet_loss=10, max_latency=750):
        self._type = None
        self._source = source
        self._destination = destination
        self._start_time = None
        self._end_time = None
        self._bw = bw
        self._priority = priority
        self._max_latency = max_latency
        self._max_packet_loss = max_packet_loss
        self._path = None
        self.minimum_bandwidth(max_packet_loss)

    @property
    def bw(self):
        return self._bw
    @property
    def source(self):
        return self._source
    @property
    def destination(self):
        return self._destination
    @property
    def path(self):
        return self._path
    @property
    def priority(self):
        return self._priority
    @bw.setter
    def bw(self, given_bw):
        self._bw = given_bw
    @source.setter
    def source(self, given_source):
        self._source = given_source
    @destination.setter
    def destination(self, given_destination):
        self._destination = given_destination
    @priority.setter
    def priority(self, given_priority):
        self._priority = given_priority
    @path.setter
    def path(self, path):
        self._path = deepcopy(path)

    @property
    def max_latency(self):
        return self._max_latency
    
    @max_latency.setter
    def max_latency(self, given_max_latency):
        self._max_latency = given_max_latency
        
    #@_min_bw.setter
    def minimum_bandwidth(self, max_packet_loss):
        self._min_bw = self._bw*(1-0.01*max_packet_loss)
    @property
    def min_bw(self):
        return self._min_bw

    @property
    def max_packet_loss(self):
        return self._max_packet_loss
    
