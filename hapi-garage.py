#!/usr/bin/env python3

import os
import sys
import logging
import signal
import argparse
import json

from pyhap.accessory_driver import AccessoryDriver
import pyhap.loader as loader

from accessories.GarageDoor import GarageDoor


DEFAULT_CONFIG = {
    "version": 1,
    "log_level": "DEBUG",
    "gpio": {
        "mode": "board"
    },
    "driver": {
        "address": None,
        "port": 51826,
        "pincode": None,
        "persist_file": "~/.hapi-garage/garage.state"
    },
    "doors": []
}


def parse_args():
    '''parse_args'''
    parser = argparse.ArgumentParser(prog="hapi-garage", description="HomeKit Pi Garage Door Opener")
    parser.add_argument("-c", "--config", action="store", default="~/.hapi-garage/config.json",
                        help="config to load")
    parser.add_argument("-l", "--log-level", action="store", default="INFO",
                        help="set logging level")
    parser.add_argument("--reset", action="store_true", help="delete pairing information")
    parser.add_argument("--nuke", action="store_true", help="reset everything, all is lost...")

    return vars(parser.parse_args())

def load_config(filename):
    '''load_config'''
    filename = os.path.expanduser(filename)
    config = DEFAULT_CONFIG
    try:
        with open(filename) as fdc:
            config = json.load(fdc)
    except IOError:
        logging.warn("missing config: {0}".format(filename))

    return config

def parse_config(cargs):
    '''parse_config:
    convert known string values to their internal representation'''
    return cargs

def merge_configs(cli_args, file_args):
    '''merge_configs'''
    file_args.update(cli_args)
    return file_args

def validate_config(args):
    '''validate_config'''
    pass

def do_reset(args):
    print("WARNING!!! About to delete pairing info!")
    response = raw_input("Do you wish to continue? [yes/NO]: ")
    if response.lower() == "yes":
        print("deleting {0}".format(args["driver"]["persist_file"]))

def do_nuke(args):
    print("WARNING!!! About to delete all configs!")
    response = raw_input("Do you wish to continue? [yes/NO]: ")
    if response.lower() == "yes":
        print("deleting {0}".format(args["config"]))
        print("deleting {0}".format(args["driver"]["persist_file"]))

def main():
    '''main'''
    logging.basicConfig(level=logging.WARNING)

    pargs = parse_args()
    cargs = load_config(pargs["config"])

    cargs = parse_config(cargs)
    args = merge_configs(pargs, cargs)
    validate_config(args)

    # handle any immediate actions and exit
    if args["reset"]:
        do_reset(args)
        return 0

    if args["nuke"]:
        do_nuke(args)
        return 0

    # we should have a fully supported set of args...no need to check
    # for key exists, since everything should be in place
    logging.getLogger().setLevel(getattr(logging, args["log_level"].upper()))

    # Start the accessory on port 51826
    driver = AccessoryDriver(address=args["driver"]["address"],
                             port=args["driver"]["port"],
                             persist_file=args["driver"]["persist_file"],
                             pincode=args["driver"]["pincode"])

    GarageDoor.setup(args["gpio"]["mode"])
    for door in args["doors"]:
        driver.add_accessory(accessory=GarageDoor(driver, door["name"], **door))

    # We want SIGTERM (kill) to be handled by the driver itself,
    # so that it can gracefully stop the accessory, server and advertising.
    signal.signal(signal.SIGTERM, driver.signal_handler)

    # Start it!
    driver.start()

    return 0

if __name__ == "__main__":
    sys.exit(main())
