import time
import tempfile
import numpy as np
from pathlib import Path
from dataclasses import dataclass
import sys
import os
sys.path.append(os.path.join('..','src'))
import plotting
import bz2
import _pickle as cPickle
import pickle
import sac_tri

"""
This module contains support and extra functions.
"""

class MeasureDuration:
    """ Used to measure the duration of a block of code.

    to use this:
    with MeasureDuration() as m:
        #code to measure
    """
    def __init__(self, what_str=""):
        self.start = None
        self.end = None
        self.what_str = what_str
    def __enter__(self):
        self.start = time.time()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end = time.time()
        print(f"Time:  {self.duration()}  for {self.what_str}")
    def duration(self):
        return str((self.end - self.start)) + ' s'

@dataclass
class SacTrainState:
    """
    Data class. It is used internally by sac.SacTrain and sac_tri.SacTrain to save the internal
    training state. When saving and loading a training session, it is pickled and unpickled.
    """
    device = None
    save_data_dir = None
    env_params = None
    training_hyperparams = None
    log_info = None
    state = None
    log_session = None
    steps_done = None
    running_reward = None
    running_loss = None
    actions = None
    running_multi_obj = None

class LogSession(object):
    """
    Data object used to store the location of all the logging and training state data.
    It is used internally by sac.SacTrain and sac_tri.SacTrain to handle training state saving 
    and logging.
    """
    def __init__(self, log_dir, state_dir, log_running_reward, log_running_loss, log_running_multi_obj,
                    log_actions,running_reward_file, running_loss_file,running_multi_obj_file, actions_file):
        self.log_dir = log_dir
        self.state_dir = state_dir
        self.log_running_reward = log_running_reward
        self.log_running_loss = log_running_loss
        self.log_running_multi_obj = log_running_multi_obj
        self.log_actions = log_actions
        self.running_reward_file = running_reward_file
        self.running_loss_file = running_loss_file
        self.running_multi_obj_file = running_multi_obj_file
        self.actions_file = actions_file

def test_policy(env_class, env_params, policy, gamma, is_tri, steps=2000, env_state = None, suppress_show=False,
                actions_to_plot=400, save_policy_to_file_name=None, actions_ylim=None, dont_clear_output=False):
    """
    Function to test the performance of a given policy. It creates a new instance of the environment, eventually
    at a given initial state, and performs a given number of steps recording the reward and computing the running 
    return weighed by some given gamma (not necessarily the same gamma as training). It then returns the running 
    return, and eventually plots the return and the last actions takes. It can also save the chosen actions to file
    Works both for sac and sac_tri (so both for the continuous and discrete + continuous case)

    Args:
        env_class: class of the environment
        env_params(dict): dictionary of parameters to initialize the environment
        policy: the policy to test, i.e. a function taking a state as input, and outputting an action
        gamma (float): the discount factor used to compute the average return
        is_tri (bool): if the environment also has discrete actions (True) 
        steps (int): number of steps to perform on the environment
        env_state: initial state of the environment. If None, it will be chosen by env_class
        suppress_show (bool): if False, it will plot the running return and the last chosen actions
        actions_to_plot (int): how many of the last actions to show in the plot
        save_policy_to_file_name (str): if specified, it will save the chosen actions to this file
        actions_ylim ((float,float)): y_lim for the plot of the chosen actions

    Returns:
        (float): final value of the running return

    """
    #create an instance of the environment
    env = env_class(env_params)
    state = env.reset()
    #if env_state was specfified, we load it
    if env_state is not None:
        env.set_current_state(env_state)
        state = env_state
    #initialize variables to compute the running reward without bias, and to save the actions
    running_reward = 0.
    running_multi_obj = None
    o_n = 0.
    running_rewards = []
    running_multi_objs = []
    actions = []
    
    try: 
        rhofx, rhofz = env.state.rhofx, env.state.rhofz
    except:
        rhofx, rhofz = 0., env.get_z_coordinate(env.state.p)
    
    info = {"rhofx": [rhofx,],
            "rhofz": [rhofz,],
            "discrete_actions": [], 
            "continuous_actions": [],
            "rewards": []}
    #loop to interact with the environment 
    for i in range(steps):
        act = policy(state)
        info["discrete_actions"].append(act[0])
        info["continuous_actions"].append(act[1].item())
        state,ret,_, info_dict =  env.step(act)
        try:
            info["rhofx"].append(env.state.rhofx)
            info["rhofz"].append(env.state.rhofz)
        except:
            info["rhofx"].append(0.)
            info["rhofz"].append(env.get_z_coordinate(env.state.p))
            
        info["rewards"].append(ret)
        o_n += (1.-gamma)*(1.-o_n)
        running_reward += (1.-gamma)/o_n*(ret - running_reward)
        running_rewards.append([i,running_reward])
        if is_tri:
            actions.append([i] + [act[0]] + list(act[1])) 
        else:
            actions.append([i] +  list(act))
        #running average of multi-obejctives (if they exist)
        if "multi_obj" in info_dict:
            if running_multi_obj is None:
                running_multi_obj = np.zeros(len(info_dict["multi_obj"]))
            running_multi_obj += (1.-gamma)/o_n*(info_dict["multi_obj"] - running_multi_obj)
            running_multi_objs.append([i] + list(running_multi_obj)) 

    #if necessary, saves the chosen actions to file
    if save_policy_to_file_name is not None:
        f_actions_name = save_policy_to_file_name
        Path(f_actions_name).parent.mkdir(parents=True, exist_ok=True)
    else:
        f_actions_name = None

    #if we need to plot the rewards and actions
    if not suppress_show:
        #save data to a temp file in order to cal the plotting functions which loads data from files
        f_running_rewards = tempfile.NamedTemporaryFile()
        f_running_rewards_name = f_running_rewards.name
        f_running_rewards.close()
        if f_actions_name is None:
            f_actions = tempfile.NamedTemporaryFile()
            f_actions_name = f_actions.name
            f_actions.close()
        np.savetxt(f_running_rewards_name, np.array(running_rewards))
        np.savetxt(f_actions_name, np.array(actions))

        #if its multi_objective, i save that file too
        if not running_multi_obj is None:
            f_running_multi_objs = tempfile.NamedTemporaryFile()
            f_running_multi_objs_name = f_running_multi_objs.name
            f_running_multi_objs.close()
            np.savetxt(f_running_multi_objs_name, np.array(running_multi_objs))
        
        plotting.plot_sac_logs(Path(f_running_rewards_name).parent.name, running_reward_file=f_running_rewards_name,
            running_loss_file=None,  running_multi_obj_file= f_running_multi_objs_name , actions_file=f_actions_name, actions_per_log=1,
            plot_to_file_line = None, suppress_show=False, save_plot = False, extra_str="",is_tri=is_tri,
            actions_to_plot=actions_to_plot,actions_ylim=actions_ylim,dont_clear_output=dont_clear_output)
    return running_reward, info if running_multi_obj is None else np.concatenate([np.array([running_reward]), running_multi_obj]), info

def pickle_data(file_location, data):
    """
    saved an object to file compressing it with bz2

    Args:
        file_location (str): where the file should be stored
        data(obj): data to be saved
    """
    with bz2.BZ2File(file_location, "w") as f: 
        cPickle.dump(data, f)

def unpickle_data(file, uncompressed_file = None):
    """
    Loads the file and return the unpickled data.

    Args:
        file(str): the compressed file to load
        uncompressed_file(str): if specified, it loads it as an uncompressed file if it cant find file
    """
    #if the compressed file exists
    if os.path.exists(file):
        data = bz2.BZ2File(file, "rb")
        data = cPickle.load(data)
    else:
        #if the uncompressed file must be loaded
        with open(uncompressed_file, 'rb') as input:
            data = pickle.load(input)

    return data
    
def log_dirs_given_criteria(main_dir, conditions_dict):
    """
    returns a list of directories with logs satisfying all parameter requests given in conditions_dict

    Args:
    main_dir (str): location of the directory containing all log directories
    conditions_dict (dict): dictionary with all parameter requests to be satisfied

    Return:
        list of log directories satisfying the requests
    """
    ret_list = []
    #loop through all folders
    for sub_dir in os.listdir(main_dir):
        #current log directory
        log_dir = os.path.join(main_dir,sub_dir)
        #check if it's a folder and not a file
        if os.path.isdir(log_dir):     
            #load all parameters in a dict
            params_dict = params_from_log_dir(log_dir)
            all_conditions_met = True
            #check if all conditions are met
            for key in conditions_dict:
                if conditions_dict[key] != params_dict[key]:
                    all_conditions_met = False
                    break
            if all_conditions_met:
                ret_list.append(log_dir)
    return ret_list

def ret_last_rewards_and_avg(log_dir, number_of_rewards=3):
    """
    Given a log folder, it takes the last number_of_rewards rewards and returns them together
    with their average

    Args:
        log_dir (str): path to the log directory
        number_of_rewards(int): number of rewards to return and average

    Returns:
        last_rewards (np.array): array with the last number_of_rewards rewards
        avg (float): average of last_rewards
    """
    #load running rewards
    file = os.path.join(log_dir, sac_tri.SacTrain.RUNNING_REWARD_FILE_NAME)
    data = np.loadtxt(file)
    #extract the last rewards
    last_rewards = data[-number_of_rewards:,1]

    return (last_rewards, np.mean(last_rewards))

def params_from_log_dir(log_dir):
    """
    given a log_dir, it returns a dictionary with all the parameters loaded.
    Both key and value are strings.
    """
    #initialize dict
    params_dict = {}
    #load a dictionary with all parameters
    params_file = os.path.join(log_dir, sac_tri.SacTrain.PARAMS_FILE_NAME)
    params_np = np.genfromtxt(params_file, dtype=str, delimiter=":\t")
    for (key, value) in params_np:
        params_dict[key] = value
    return params_dict

def generate_action_times(time_list, dact_list, uact_list, target_dact):
    """
    Generates a list of times from time list for which a given action was performed.
    Returns a tuple with
    - list of these times
    - list of continuous actions performed at these times
    
    Parameters:
    time_list - list with time-stamps
    dact_list - list with discrete actions
    uact_list - list with continuous actions
    target_dact - target disctrete action (integer). Usual convention
        0 for thermalization
        1 for measurement 
        2 for feedback
    """
    final_times, final_uacts = [], []
    for idx, dact in enumerate(dact_list):
        if dact == target_dact:
            final_times.append(time_list[idx])
            final_uacts.append(uact_list[idx])
    
    return final_times, final_uacts

def get_action_idxs(dact_list, target_action):
    """
    Returns a list of indexes for which a given action was performed
    """
    idx_list = []
    for idx, dact in enumerate(dact_list):
        if dact == target_action:
            idx_list.append(idx)
            
    return idx_list

