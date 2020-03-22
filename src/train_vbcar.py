"""
Created on Aug 5, 2019
Updated on XX,2019 BY xxx@

Classes describing datasets of user-item interactions. Instances of these
are returned by dataset fetching and dataset pre-processing functions.

@author: Zaiqiao Meng (zaiqiao.meng@gmail.com)

"""
import os
import sys
import argparse
from ray import tune
from train_engine import TrainEngine,print_dict
from models.vbcar import VBCAREngine
from utils.monitor import Monitor
from utils import logger, data_util
from utils.constants import *
from tqdm import tqdm


def parse_args():
    parser = argparse.ArgumentParser(description="Run VBCAR..")
    parser.add_argument(
        "--config_file",
        nargs="?",
        type=str,
        default="../configs/vbcar_default.json",
        help="Specify the config file name. Only accept a file from ../configs/",
    )
    # If the following settings are specified with command line,
    # these settings will be updated.
    parser.add_argument(
        "--dataset",
        nargs="?",
        type=str,
        help="Options are: tafeng, dunnhunmby and instacart",
    )
    parser.add_argument(
        "--data_split",
        nargs="?",
        type=str,
        help="Options are: leave_one_out and temporal",
    )
    parser.add_argument(
        "--root_dir", nargs="?", type=str, help="working directory",
    )
    parser.add_argument(
        "--percent",
        nargs="?",
        type=float,
        help="The percentage of the subset of the dataset, only availbe on instacart dataset.",
    )
    parser.add_argument(
        "--n_sample", nargs="?", type=int, help="Number of sampled triples."
    )
    parser.add_argument(
        "--temp_train",
        nargs="?",
        type=int,
        help="IF this value >0, then the model will be trained based on the temporal feeding, else use normal trainning. Same as the time step.",
    )
    parser.add_argument(
        "--emb_dim", nargs="?", type=int, help="Dimension of the embedding."
    )
    parser.add_argument(
        "--late_dim", nargs="?", type=int, help="Dimension of the latent layers.",
    )
    parser.add_argument("--lr", nargs="?", type=float, help="Intial learning rate.")
    parser.add_argument("--num_epoch", nargs="?", type=int, help="Number of max epoch.")

    parser.add_argument(
        "--batch_size", nargs="?", type=int, help="Batch size for training."
    )
    parser.add_argument("--optimizer", nargs="?", type=str, help="OPTI")
    parser.add_argument("--activator", nargs="?", type=str, help="activator")
    parser.add_argument("--alpha", nargs="?", type=float, help="ALPHA")

    return parser.parse_args()


"""
update hyperparameters from command line
"""


def update_args(config, args):
    #     print(vars(args))
    print("Received parameters form comand line:")
    for k, v in vars(args).items():
        if v != None:
            config[k] = v
            print(k, "\t", v)


class VBCAR_train(TrainEngine):
    def __init__(self, config):
        self.config = config
        super(VBCAR_train, self).__init__(self.config)
        self.sample_triple()
        self.config["alpha_step"] = (1 - self.config["alpha"]) / (
            self.config["num_epoch"]
        )
        self.engine = VBCAREngine(self.config)

    def train(self):
        assert hasattr(self, "engine"), "Please specify the exact model engine !"
        monitor = Monitor(log_dir=self.config["run_dir"], delay=1, gpu_id=self.gpu_id)
        """
        init model
        """
        print("init model ...")
        self.engine.data = self.data
        print("strat traning... ")
        best_performance = 0
        n_no_update = 0
        epoch_bar = tqdm(range(self.config["num_epoch"]), file=sys.stdout)
        for epoch in epoch_bar:
            print("Epoch {} starts !".format(epoch))
            print("-" * 80)
            data_loader = self.build_data_loader()
            self.engine.train_an_epoch(data_loader, epoch_id=epoch)
            result = self.engine.evaluate(self.data.validate[0], epoch_id=epoch)
            test_result = self.engine.evaluate(self.data.test[0], epoch_id=epoch)
            self.engine.record_performance(result, test_result, epoch_id=epoch)
            if result[self.config["validate_metric"]] > best_performance:
                n_no_update = 0
                print_dict(result)
                self.engine.save_checkpoint(model_dir=self.config["model_ckp_file"])
                best_performance = result[self.config["validate_metric"]]
            else:
                n_no_update += 1

            if n_no_update >= MAX_N_UPDATE:
                print(
                    "Early stop criterion triggered, no performance update for {:} times".format(
                        MAX_N_UPDATE
                    )
                )
                break
            """Sets the learning rate to the initial LR decayed by 10 every 10 epochs"""
            lr = self.config["lr"] * (0.5 ** (epoch // 10))
            self.engine.model.alpha += self.config["alpha_step"]
            for param_group in self.engine.optimizer.param_groups:
                param_group["lr"] = lr
        self.config["run_time"] = monitor.stop()
        return best_performance


def tune_train(config):
    VBCAR = VBCAR_train(config)
    best_performance = VBCAR.train()
    tune.track.log(best_ndcg=best_performance)
    VBCAR.test()


if __name__ == "__main__":
    args = parse_args()
    config = {}
    update_args(config, args)
    VBCAR = VBCAR_train(config)
    VBCAR.train()
    VBCAR.test()