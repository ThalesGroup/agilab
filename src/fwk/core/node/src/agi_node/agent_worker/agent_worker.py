"""
Module rapids_worker extension of agilab-core

    Auteur: Jean-Pierre Morard

"""

######################################################
# Agi Framework call back functions
######################################################

# Internal Libraries:
import warnings
from agi_node.agi_dispatcher import BaseWorker
import logging
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class AgentWorker(BaseWorker):
    """
    AgiAgentWorker Class

    Inherits from:
        Worker: Provides foundational worker functionalities.
    """

    pass