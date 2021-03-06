import torch 
import numpy as np 
import torch.nn as nn 
import torch.nn.functional as F 
import torch.optim as optim 
import gym 
from torch.distributions import Normal 
from torch.utils.data import Dataset, DataLoader 
from collections import deque 
import pandas as pd 
import matplotlib.pyplot as plt 

env = gym.make('Pendulum-v0')
obs_size = env.observation_space.shape[0]
ac_size = env.action_space.shape[0]
max_action = env.action_space.high[0]


def discount_rewards(rewards, discount = 0.99): 
    discounted = np.zeros_like(rewards)
    r = 0.
    for i in reversed(range(len(rewards))): 
        discounted[i] = discount * r + rewards[i]
        r = discounted[i]

    return discounted

class XPDataset(Dataset): 

    def __init__(self, states, rewards, actions): 
        super().__init__()
        self.s = states 
        self.r = rewards
        self.a = actions 

    def __len__(self): 
        return len(self.r)
    def __getitem__(self, idx): 

        s = torch.tensor(self.s[idx]).float().reshape(-1)
        a = torch.tensor(self.a[idx]).float().reshape(-1)
        r = torch.tensor(self.r[idx]).float().reshape(-1)

        return s,a,r

get_loader = lambda x : DataLoader(x, batch_size = 64, shuffle = True)

class Policy(nn.Module): 

    def __init__(self, obs, ac, hidden = 64): 
        super().__init__()

        self.l1 = nn.Sequential(nn.Linear(obs, hidden), 
                                nn.Tanh(), 
                                nn.Linear(hidden,hidden), 
                                nn.Tanh())
        self.mean_head = nn.Linear(hidden, ac)
        # self.log_std_head = nn.Linear(hidden, ac)
        self.log_std = nn.Parameter(torch.zeros(ac))

    def forward(self, state): 

        l1 = self.l1(state)
        mean = self.mean_head(l1)
        # std = self.log_std_head(l1).clamp(-20,2).exp()
        return mean, self.log_std.exp()

policy = Policy(obs_size, ac_size)
value = nn.Sequential(nn.Linear(obs_size, 64), 
                      nn.ReLU(), 
                      nn.Linear(64, 64), 
                      nn.ReLU(), 
                      nn.Linear(64,1))

adam_v = optim.Adam(value.parameters(), lr = 3e-3, weight_decay = 1e-2)
adam_p = optim.Adam(policy.parameters(), lr = 3e-4)


def train(loader): 

    s_mean, s_max, s_min = 0.,0.,0.
    for counter, data in enumerate(loader): 
        s, a, r = data 
        
        state_estimates = value(s)
        value_loss = F.mse_loss(state_estimates, r)
        
        adam_v.zero_grad()
        value_loss.backward()
        adam_v.step()

        mean, std = policy(s)
        dist = Normal(mean, std)
        log_probs = dist.log_prob(a)
        policy_loss = -(log_probs * (r - state_estimates.detach())).mean()
        adam_p.zero_grad()
        policy_loss.backward()
        adam_p.step()

        s_mean += r.mean()
        s_max += r.max()
        s_min += r.min()

    return state_estimates.mean().item(), value_loss.item(), s_mean/counter, s_max/counter, s_min/counter




episodes = 10000
latest_rewards = deque(maxlen = 20)
track_rewards = deque(maxlen=10000)

for episode in range(episodes): 

    s = env.reset()
    done = False 
    states, actions, rewards = [],[],[]
    ep_rewards = 0.
    while not done: 

        with torch.no_grad(): 
            mean, std = policy(torch.tensor(s).float().reshape(1,-1))
            dist = Normal(mean, std) 
            a = dist.sample().numpy().flatten()

        ns, r, done, _ = env.step(a * max_action)
        states.append(s)
        rewards.append(r)
        actions.append(a)

        s = ns 
        ep_rewards += r

        track_rewards.append(r)

    rewards = (np.array(rewards) - np.mean(track_rewards))/np.std(track_rewards)
    rewards_to_go = discount_rewards(rewards)
    loader = get_loader(XPDataset(states, rewards_to_go, actions))
    train_data = train(loader)
    latest_rewards.append(ep_rewards)
    if episode % 5 == 0: 
        print('MeanR: {:.1f} R: {:.1f} - MeanVal: {:.2f} - ValLoss: {:.2f} - Reward: {:.3f} {:.3f} {:.3f}'.format(np.mean(latest_rewards), latest_rewards[-1], *train_data))
    
    # if episode % 100 == 0 and episode > 0: 
    #     df = pd.DataFrame(rewards, columns = ['rewards'])
    #     df.rewards.hist()
    #     plt.show()

