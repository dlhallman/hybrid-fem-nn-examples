from fenics import *
from fenics_adjoint import *

import argparse
import ufl
import time
from numpy.random import seed, randn

from ufl_dnn.neural_network import ANN, sigmoid

from shared_code.training import train, RobustReducedFunctional
from shared_code.experiment import Experiment
from shared_code.data import Dataset, DeterministicSubsampler

from model import Model
from functional import Functional


# Parse arguments
parser = argparse.ArgumentParser()
parser.add_argument("-nx", type=int, dest="nx", default=10,
                        help="The number of FE cells to discretise the mesh into in each spatial dimension.")
parser.add_argument("--seed", type=int, dest="seed", default=int(time.time()),
                    help="The random seed to use for the model initialization. "
                         "This is used to ensure the different networks have the same initial weights.")
parser.add_argument("--layers", type=int, nargs="+", default=[2, 30, 1],
                    help="A list of the width of the layers. " 
                         "Make sure input and output is compatible with the chosen model.")
parser.add_argument("--bias", type=bool, nargs="+", default=[True, True],
                    help="A list enabling/disabling bias for each layer (minus input layer).")
parser.add_argument("--maxiter", type=int, default=100, help="Maximum iterations of the optimization loop.")
parser.add_argument("--name", "-n", type=str, dest="name", default=None,
                    help="Name of experiment. Default is a random UUID.")
parser.add_argument("--eid", type=str, dest="eid", default=None,
                    help="Name of previous experiment to continue from.")
args = parser.parse_args()

seed(args.seed)

data_function = Function(Model(Nx=200, order=2).function_space)
model = Model(Nx=args.nx)
obs_func = Function(model.function_space)

# Psuedo timestep (to match dataset interface)
t0, t1 = (0., 1.)
dt = 1.0

# Load data
dataset = Dataset("data/data.xdmf", t0, t1, dt, 1, obs_func=data_function)
obs = dataset.read(obs_func, t1)
n = FacetNormal(model.mesh)
x, y = SpatialCoordinate(model.mesh)
boundary_data = model.ground_truth(x, y) * inner(n, grad(obs))

functional = Functional(boundary_data, n)

# Construct neural network
bias = args.bias
layers = args.layers
activation = sigmoid
net = ANN(layers, bias=bias, sigma=activation, init_method="uniform")

if args.eid is not None:
    experiment = Experiment(args.eid)
    net = experiment.NN
    net.output_activation = None
else:
    experiment = Experiment()
    experiment.NN = net
    experiment.seed = seed
experiment.args = args

model.forward(obs, net, functional)

J = functional.J
Jhat = RobustReducedFunctional(J, net.weights_ctrls())

set_log_level(LogLevel.ERROR)
weights, loss = train(Jhat, maxiter=args.maxiter, tol=1e-200, gtol=1e-12)

with stop_annotating():
    net.set_weights(weights)

weights, loss = train(Jhat, method="TNC", maxiter=args.maxiter, tol=1e-200, gtol=1e-12)

with stop_annotating():
    net.set_weights(weights)

experiment.loss = loss
if args.name is not None:
    experiment.id = args.name
experiment.save()
