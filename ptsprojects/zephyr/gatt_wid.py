#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2017, Intel Corporation.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#

import logging
import sys
from pybtp import btp
import re
import struct
from binascii import hexlify
from pybtp.types import Prop, Perm, IOCap
from ptsprojects.stack import get_stack

log = logging.debug


def gatt_wid_hdl(wid, description, test_case_name):
    log("%s, %r, %r, %s", gatt_wid_hdl.__name__, wid, description,
        test_case_name)
    module = sys.modules[__name__]

    try:
        handler = getattr(module, "hdl_wid_%d" % wid)
        return handler(description)
    except AttributeError as e:
        logging.exception(e.message)


# wid handlers section begin
def hdl_wid_1(desc):
    btp.gap_set_conn()
    btp.gap_set_gendiscov()
    btp.gap_adv_ind_on()
    return True


def hdl_wid_4(desc):
    btp.gap_set_io_cap(IOCap.no_input_output)
    return True


def hdl_wid_17(desc):
    # This pattern is matching Primary Service
    pattern = re.compile(r"Service\s=\s'([0-9a-fA-F]+)'")
    pts_services = pattern.findall(desc)
    if not pts_services:
        logging.error("%s parsing error", hdl_wid_17.__name__)
        return False

    # Normalize UUIDs
    pts_services = [hex(int(service, 16)) for service in pts_services]

    iut_services = []

    # Get all primary services
    attrs = btp.gatts_get_attrs(type_uuid='2800')
    for attr in attrs:
        handle, perm, type_uuid = attr
        (_, uuid_len, uuid) = btp.gatts_get_attr_val(handle)
        uuid = btp.btp2uuid(uuid_len, uuid)
        iut_services.append(uuid)

    # Verification
    for service in pts_services:
        if service in iut_services:
            iut_services.remove(service)
            logging.debug("Service %s found", service)
            continue
        else:
            logging.error("Service %s not found", service)
            return False
    return True


def hdl_wid_23(desc):
    # This pattern is matching Primary Service
    uuid_pattern = re.compile(r"UUID\s?=\s'([0-9a-fA-F]+)'")
    start_hdl_pattern = re.compile(r"start\shandle\s=\s'([0-9a-fA-F]+)'")
    end_hdl_pattern = re.compile(r"end\shandle\s=\s'([0-9a-fA-F]+)'")

    uuids = uuid_pattern.findall(desc)
    start_hdls = start_hdl_pattern.findall(desc)
    end_hdls = end_hdl_pattern.findall(desc)

    # Normalize
    uuids = [hex(int(uuid, 16)) for uuid in uuids]
    start_hdls = [int(hdl, 16) for hdl in start_hdls]
    end_hdls = [int(hdl, 16) for hdl in end_hdls]
    pts_services = [list(a) for a in zip(start_hdls, end_hdls, uuids)]
    iut_services = []

    # [start_hdl, end_hdl, uuid]
    iut_service = None

    # Get all primary services
    attrs = btp.gatts_get_attrs(type_uuid='2800')
    for attr in attrs:
        start_handle, perm, type_uuid = attr

        if iut_service is not None:
            iut_service[1] = start_handle - 1
            iut_services.append(iut_service)
            iut_service = None

        val = btp.gatts_get_attr_val(start_handle)
        if not val:
            continue

        (_, uuid_len, uuid) = val
        iut_service = [start_handle, "unknown", btp.btp2uuid(uuid_len, uuid)]

    iut_services.append(iut_service)

    # Verification
    for service in pts_services:
        if service in iut_services:
            iut_services.remove(service)
            logging.debug("Service %r found", service)
            continue
        else:
            logging.error("Service %r not found", service)
            return False

    return True


def hdl_wid_24(desc):
    # This pattern is matching Attribute Handle, Included Service Attribute handle, End Group Handle, Service UUID
    data_pattern = re.compile(r"'([0-9a-fA-F]+)'")
    pts_data = data_pattern.findall(desc)

    # Normalize
    pts_data = [hex(int(d, 16)) for d in pts_data]
    iut_data = []

    # Get all primary services
    attrs = btp.gatts_get_attrs(type_uuid='2802')
    for attr in attrs:
        handle, perm, type_uuid = attr

        val = btp.gatts_get_attr_val(handle)
        if not val:
            continue

        (att_rsp, value_len, value) = val

        if value_len == 6:
            (incl_svc_hdl, end_grp_hdl, uuid) = struct.unpack("<HHH", value)
            iut_data.append([hex(handle), hex(incl_svc_hdl), hex(end_grp_hdl), hex(uuid)])
        else:
            # TODO
            return False

    logging.debug("%r %r", pts_data, iut_data)

    if pts_data in iut_data:
        logging.debug("Service %r found", pts_data)
        return True
    else:
        logging.error("Service %r not found", pts_data)
        return False


def hdl_wid_25(desc):
    # Please confirm IUT have following characteristics in services UUID= '1801'O handle='0002'O handle='0005'O
    # handle='0007'O
    pattern = re.compile(r"(UUID|handle)\s?=\s?'([0-9a-fA-F]+)'")
    pts_data = pattern.findall(desc)
    if not pts_data:
        logging.error("parsing error")
        return False

    pts_chrc_uuid = None
    pts_chrc_handles = []

    for d in pts_data:
        if d[0] == 'UUID':
            pts_chrc_uuid = hex(int(d[1], 16))
        else:
            pts_chrc_handles.append(int(d[1], 16))

    iut_start_handle = None
    iut_end_handle = None

    # Find pts_chrc_uuid service and it's handle range
    svcs = btp.gatts_get_attrs(type_uuid='2800')
    for svc in svcs:
        handle, perm, type_uuid = svc

        if iut_start_handle:
            iut_end_handle = handle - 1
            break

        svc_val = btp.gatts_get_attr_val(handle)
        if not svc_val:
            continue

        att_rsp, uuid_len, uuid = svc_val
        if btp.btp2uuid(uuid_len, uuid) == pts_chrc_uuid:
            iut_start_handle = handle

    if iut_start_handle is None or iut_end_handle is None:
        logging.error("service %s not found", pts_chrc_uuid)
        return False

    iut_chrc_handles = []

    # Lookup all services within service range
    chrcs = btp.gatts_get_attrs(type_uuid='2803',
                                start_handle=iut_start_handle,
                                end_handle=iut_end_handle)
    for chrc in chrcs:
        handle, perm, type_uuid = chrc
        iut_chrc_handles.append(handle)

    if iut_chrc_handles != pts_chrc_handles:
        return False

    return True


def hdl_wid_52(desc):
    # This pattern is matching IUT handle and characteristic value
    pattern = re.compile("(Handle|value)='([0-9a-fA-F]+)'")
    params = pattern.findall(desc)
    if not params:
        logging.error("%s parsing error", hdl_wid_52.__name__)
        return False

    params = dict(params)

    handle = int(params.get('Handle'), 16)
    value = int(params.get('value'), 16)

    (att_rsp, value_len, value_read) = btp.gatts_get_attr_val(handle)
    value_read = int(hexlify(value_read), 16)

    if value_read != value:
        return False
    return True


def hdl_wid_56(desc):
    # This pattern is matching multiple IUT handle and characteristic value
    pattern = re.compile("'([0-9a-fA-F]+)'")
    params = pattern.findall(desc)
    if not params or len(params) != 3:
        logging.error("parsing error")
        return False

    handle1 = params[0]
    handle2 = params[1]
    values = params[2]

    values_read = ""

    att_rsp, value_len, value = btp.gatts_get_attr_val(handle1)
    values_read += hexlify(value)

    att_rsp, value_len, value = btp.gatts_get_attr_val(handle2)
    values_read += hexlify(value)

    if values_read.upper() != values.upper():
        return False

    return True


def hdl_wid_75(desc):
    # This pattern is matching IUT handle and characteristic value
    pattern = re.compile("(handle|value)\s?=\s?'([0-9a-fA-F]+)'")
    params = pattern.findall(desc)
    if not params:
        logging.error("parsing error")
        return False

    params = dict(params)

    handle = int(params.get('handle'), 16)
    value = int(params.get('value'), 16)

    stack = get_stack()

    val = stack.gatt.wait_attr_value_changed(handle, 10)
    if val is None:
        return False

    val = int(val, 16)

    return val == value


def hdl_wid_110(desc):
    # Lookup characteristic handle that does not permit reading
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        if not (perm & Perm.read) or not (prop & Prop.read):
            return '{0:04x}'.format(handle, 'x')

    return '0000'


def hdl_wid_111(desc):
    # Lookup characteristic UUID that does not permit reading
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        if not (perm & Perm.read) or not (prop & Prop.read):
            uuid_str = btp.btp2uuid(uuid_len, chrc_uuid)
            if uuid_len == 2:
                return format(int(uuid_str, 16), 'x').zfill(4)
            else:
                return uuid_str

    return '0000'


def hdl_wid_112(desc):
    # Lookup characteristic handle that requires read authorization
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        (att_rsp, val_len, val) = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        chrc_value_data = btp.gatts_get_attr_val(handle)
        if not chrc_value_data:
            continue

        # Check if returned ATT Insufficient Authorization error
        att_rsp, val_len, val = chrc_value_data
        if att_rsp != 8:
            continue

        return '{0:04x}'.format(handle, 'x')

    return '0000'


def hdl_wid_113(desc):
    # Lookup characteristic UUID that requires read authorization
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_data = btp.gatts_get_attr_val(handle)
        if not chrc_data:
            continue

        att_rsp, val_len, val = chrc_data

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        chrc_value_data = btp.gatts_get_attr_val(handle)
        if not chrc_value_data:
            continue

        att_rsp, val_len, val = chrc_value_data

        # Check if returned ATT Insufficient Authorization error
        if att_rsp != 8:
            continue

        uuid_str = btp.btp2uuid(uuid_len, chrc_uuid)
        if uuid_len == 2:
            return format(int(uuid_str, 16), 'x').zfill(4)
        else:
            return uuid_str

    return '0000'


def hdl_wid_114(desc):
    # Lookup characteristic UUID that requires read authentication
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        if perm & Perm.read_authn:
            return '{0:04x}'.format(handle, 'x')

    return '0000'


def hdl_wid_115(desc):
    # Lookup characteristic UUID that requires read authentication
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        if perm & Perm.read_authn:
            uuid_str = btp.btp2uuid(uuid_len, chrc_uuid)
            if uuid_len == 2:
                return format(int(uuid_str, 16), 'x').zfill(4)
            else:
                return uuid_str

    return '0000'


def hdl_wid_118(desc):
    # Lookup invalid attribute handle
    handle = None

    attrs = btp.gatts_get_attrs()
    for attr in attrs:
        handle, perm, type_uuid = attr

    if handle is None:
        logging.error("No attribute found!")
        return "0000"

    return '{0:04x}'.format(handle + 1, 'x')


def hdl_wid_119(desc):
    # Lookup UUID that is not present on IUT GATT Server
    uuid_list = []

    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, uuid = struct.unpack("<BH%ds" % uuid_len, val)
        uuid_list.append(btp.btp2uuid(uuid_len, uuid))

    if len(uuid_list) == 0:
        logging.error("No attribute found!")
        return "0000"

    uuid_invalid = 1

    while True:
        if format(uuid_invalid, 'x') in uuid_list:
            uuid_invalid += 1
        else:
            uuid_invalid = format(uuid_invalid, 'x').zfill(4)
            break

    return uuid_invalid


def hdl_wid_120(desc):
    # Lookup characteristic handle that does not permit write
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        att_rsp, val_len, val = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        if not (perm & Perm.write) or not (prop & Prop.write):
            return '{0:04x}'.format(handle, 'x')

    return '0000'


def hdl_wid_121(desc):
    # Lookup characteristic UUID that returns Insufficient Encryption Key Size
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_val = btp.gatts_get_attr_val(handle)
        if not chrc_val:
            continue

        (att_rsp, val_len, val) = chrc_val

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        chrc_value_data = btp.gatts_get_attr_val(handle)
        if not chrc_value_data:
            continue

        # Check if returned ATT Insufficient Authorization error
        att_rsp, val_len, val = chrc_value_data
        if att_rsp != 0x0c:
            continue

        return '{0:04x}'.format(handle, 'x')

    return '0000'


def hdl_wid_122(desc):
    # Lookup characteristic UUID that returns Insufficient Encryption Key Size
    chrcs = btp.gatts_get_attrs(type_uuid='2803')
    for chrc in chrcs:
        handle, perm, type_uuid = chrc

        chrc_data = btp.gatts_get_attr_val(handle)
        if not chrc_data:
            continue

        att_rsp, val_len, val = chrc_data

        hdr = '<BH'
        hdr_len = struct.calcsize(hdr)
        uuid_len = val_len - hdr_len

        prop, handle, chrc_uuid = struct.unpack("<BH%ds" % uuid_len, val)
        chrc_value_attr = btp.gatts_get_attrs(start_handle=handle,
                                              end_handle=handle)
        if not chrc_value_attr:
            continue

        handle, perm, type_uuid = chrc_value_attr[0]
        chrc_value_data = btp.gatts_get_attr_val(handle)
        if not chrc_value_data:
            continue

        att_rsp, val_len, val = chrc_value_data

        # Check if returned ATT Insufficient Authorization error
        if att_rsp != 0x0c:
            continue

        uuid_str = btp.btp2uuid(uuid_len, chrc_uuid)
        if uuid_len == 2:
            return format(int(uuid_str, 16), 'x').zfill(4)
        else:
            return uuid_str

    return '0000'
