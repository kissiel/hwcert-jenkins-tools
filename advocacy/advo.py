#!/usr/bin/env python3

import datetime
import json
import os
import re
import subprocess

from influxdb import InfluxDBClient


INFLUX_HOST = "10.50.124.12"


client = InfluxDBClient(
    INFLUX_HOST, 8086, 'ce', os.environ.get("INFLUX_PASS"), 'desktopsnaps')


class CurlError(Exception):
    pass


def curl(url):
    cmd = ['curl', '-s', url]
    try:
        out = subprocess.check_output(cmd)
        return out.decode('utf-8')
    except subprocess.CalledProcessError:
        raise CurlError


def set_cause_version_from_manifest(cause, manifest):
    match = re.search(fr'^{cause}(?::\w+)?\s+([^\n]+)', manifest, re.MULTILINE)
    if match:
        return match.group(1).rstrip()
    else:
        return 'N/A'


def set_cause_version_from_snap_list(cause, snap_list):
    match = re.search(fr'^{cause}\s+(\S+)\s+(\S+)\s+', snap_list, re.MULTILINE)
    if match:
        return f"{match.group(1)} ({match.group(2)})"
    else:
        return 'N/A'


def main():
    build_url = os.getenv("BUILD_URL")
    try:
        csv = curl("{}artifact/artifacts/checkbox.csv".format(build_url))
    except CurlError:
        print('Unable to fetch jenkins project information.')
    if 'snap,cold,hot' not in csv:
        raise SystemExit(1)

    url = "{}api/json".format(build_url)
    try:
        res = curl(url)
    except CurlError:
        print('Unable to fetch jenkins project information.')
    build_desc = json.loads(res)
    cause = 'Manual run'
    cause_version = 'N/A'
    try:
        cause = build_desc['actions'][0]['causes'][0]['upstreamProject']
        cause = cause.replace('advocacy-trigger-', '').replace(
            '-snaps-baseline', '').replace('-os-baseline', '')
        cause = cause.replace('-stable', '').replace('-candidate', '').replace(
            '-beta', '')
        try:
            snap_list = curl("{}artifact/artifacts/snap_list.txt".format(
                build_url))
            cause_version = set_cause_version_from_snap_list(cause, snap_list)
        except CurlError:
            snap_list = None
    except KeyError:
        try:
            cause_desc = build_desc[
                'actions'][1]['causes'][0]['shortDescription']
            if 'URLTrigger' in cause_desc:
                res = curl("{}triggerCauseAction/".format(build_url))
                m = re.search(
                    "The value for the JSON Path '(.*?)' has changed.", res)
                cause = m.group(1)
        except (KeyError, IndexError):
            print('failed to get build cause')
        except CurlError:
            print('Unable to fetch URLTrigger project information.')
        try:
            deb_manifest = curl("{}artifact/artifacts/manifest.txt".format(
                build_url))
            cause_version = set_cause_version_from_manifest(
                cause, deb_manifest)
        except CurlError:
            deb_manifest = None
    ts = build_desc['timestamp']
    date = datetime.datetime.fromtimestamp(ts/1000).strftime(
        '%Y-%m-%dT%H:%M:%SZ')
    match = re.search(r'advocacy-(\w+)-(\w+)-gfx', os.getenv("JOB_NAME"))
    if match:
        release = match.groups()[0]
        hw_id = match.groups()[1]
    else:
        raise SystemExit(1)

    snaps = {line.split(',')[0] for line in csv.splitlines()[1:]}
    for l in csv.splitlines()[1:]:
        try:
            snap, cold, hot = l.split(',')
            if hot == '-1':
                hot = 0
            if cold == '-1':
                cold = 0
            try:
                hot = float(hot)
            except ValueError:
                hot = 0.0
            try:
                cold = float(cold)
            except ValueError:
                cold = 0.0
            if cold == 0.0 or hot == 0.0:
                continue
            measurements = [{
                "measurement": "startup_time",
                "tags": {
                    "hw_id": hw_id,
                    "release": release,
                    "snap": snap,
                    "cause": cause,
                    "cause_version": cause_version,
                },
                "fields": {
                    "hot": hot,
                    "cold": cold,
                    "jenkins": '<a href="{}">Jenkins build</a>'.format(
                        build_url),
                },
                "time": date
            }]
            if cause in snaps and cause != snap:
                continue
            client.write_points(measurements)
        except ValueError:
            continue


if __name__ == '__main__':
    main()
