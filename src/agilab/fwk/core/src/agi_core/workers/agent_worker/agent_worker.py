"""
Module rapids_worker extension of agilab-core

    Auteur: Jean-Pierre Morard

"""

######################################################
# Agi Framework call back functions
######################################################

# Internal Libraries:
import os
import warnings
from agi_worker.agi_worker import AgiWorker
import logging
warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

class AgentWorker(AgiWorker):
    """
    AgiAgentWorker Class

    Inherits from:
        Worker: Provides foundational worker functionalities.
    """

    pass