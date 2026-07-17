/*
 * Xilinx SystemC/TLM-2.0 ZynqMP Wrapper.
 *
 * Written by Edgar E. Iglesias <edgar.iglesias@xilinx.com>
 *
 * Copyright (c) 2016, Xilinx Inc.
 * All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include <assert.h>
#include <stdint.h>

#include <systemc>

#include "tlm_utils/simple_initiator_socket.h"
#include "tlm_utils/simple_target_socket.h"
#include "tlm_utils/tlm_quantumkeeper.h"

using namespace sc_core;
#include "libremote-port/remote-port-tlm.h"

#include "libremote-port/remote-port-tlm-memory-master.h"
#include "libremote-port/remote-port-tlm-memory-slave.h"
#include "libremote-port/remote-port-tlm-wires.h"

template <bool> struct Range;

template <unsigned no_master, unsigned no_slaves, unsigned no_outputs,
          unsigned no_inputs, typename = Range<true>>
class QemuTLM {};

template <unsigned no_master, unsigned no_slaves, unsigned no_outputs,
          unsigned no_inputs>
class QemuTLM<no_master, no_slaves, no_outputs, no_inputs,
              Range<(no_master <= 10 && no_slaves <= 10)>>
    : public remoteport_tlm {
public:
  QemuTLM(sc_core::sc_module_name name, const char *sk_descr,
          Iremoteport_tlm_sync *sync = NULL)
      : remoteport_tlm(name, -1, sk_descr, sync),
        wire_out("wire_out", no_inputs), wire_in("wire_in", no_outputs),
        rp_wires("wires", no_outputs, no_inputs) {

    unsigned curId = 0;
    char modName[16];

    for (unsigned i = 0; i < no_master; ++i) {
      snprintf(modName, sizeof(modName), "rp_net_master%d", i);
      rp_mem_master.emplace_back(new remoteport_tlm_memory_master(modName));
      pub_mem_master[i] = &rp_mem_master[i]->sk;
      register_dev(curId++, rp_mem_master[i]);
    }

    curId = 10;
    for (unsigned i = 0; i < no_slaves; ++i) {
      snprintf(modName, sizeof(modName), "rp_net_slave%d", i);
      rp_mem_slave.emplace_back(new remoteport_tlm_memory_slave(modName));
      pub_mem_slave[i] = &rp_mem_slave[i]->sk;
      register_dev(curId++, rp_mem_slave[i]);
    }

    register_dev(20, &rp_wires);

    for (unsigned i = 0; i < no_inputs; ++i) {
      rp_wires.wires_out[i](wire_out[i]);
    }
    for (unsigned i = 0; i < no_outputs; ++i) {
      rp_wires.wires_in[i](wire_in[i]);
    }
  }
  ~QemuTLM(void){};

  void tie_off(void) { remoteport_tlm::tie_off(); };

  tlm_utils::simple_initiator_socket<remoteport_tlm_memory_master>
      *pub_mem_master[no_master];
  tlm_utils::simple_target_socket<remoteport_tlm_memory_slave>
      *pub_mem_slave[no_slaves];
  sc_core::sc_vector<sc_core::sc_signal<bool>> wire_out;
  sc_core::sc_vector<sc_core::sc_signal<bool>> wire_in;

private:
  std::vector<remoteport_tlm_memory_master *> rp_mem_master;
  std::vector<remoteport_tlm_memory_slave *> rp_mem_slave;
  remoteport_tlm_wires rp_wires;
};
