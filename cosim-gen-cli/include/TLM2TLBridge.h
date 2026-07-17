#ifndef TLM2TLBRIDGE_H__
#define TLM2TLBRIDGE_H__

#include "tilelink.h"
#include <systemc>
#include <tlm_utils/simple_target_socket.h>

template <typename bussize_t = uint64_t, typename addr_t = uint32_t,
          typename maskType_t = uint8_t, typename short_t = uint8_t,
          typename logSize_t = uint8_t, typename source_t = uint8_t,
          typename sink_t = uint8_t, bool rocketChipQuirk = true,
          bool autoConnect = true>
SC_MODULE(TLM2TLBridge) {
public:
  tlm_utils::simple_target_socket<TLM2TLBridge> targetsock;

  sc_core::sc_in<bool> clock{"clock"};
  sc_core::sc_in<bool> reset{"reset"};
  struct TLOutConnection<bussize_t, addr_t, maskType_t, short_t, logSize_t,
                         source_t, sink_t>
      c;
  TLSignals<bussize_t, addr_t, maskType_t, short_t, logSize_t, source_t, sink_t>
      signals;

  TLM2TLBridge(sc_core::sc_module_name name)
      : sc_core::sc_module(name), signals("signals") {
    targetsock.register_b_transport(this, &TLM2TLBridge::b_transport);
    if (autoConnect)
      c.connect(signals);
  }

  TLM2TLBridge(sc_core::sc_module_name name, sc_core::sc_clock & clk,
               sc_core::sc_signal<bool> & rst)
      : TLM2TLBridge(name) {
    clock(clk);
    reset(rst);
  }

  void b_transport(tlm::tlm_generic_payload & trans, sc_core::sc_time & delay) {
    wait(delay);
    wait(clock.posedge_event());

    sc_assert(!reset);

    // ToDo: Correctly check these...
    sc_assert(c.d_sink == 0);
    sc_assert(c.a_source == 0);

    tlm::tlm_command cmd = trans.get_command();
    unsigned totalLen = trans.get_data_length();
    uint8_t *data_ptr = trans.get_data_ptr();
    logSize_t log2Size = (int)log2(totalLen);
    unsigned beats = (totalLen + sizeof(bussize_t) - 1) / sizeof(bussize_t);
    unsigned accessLen = totalLen;
    if (beats > 1)
      accessLen = sizeof(bussize_t);
    maskType_t mask = (1U << accessLen) - 1;
    short_t byte_shift = trans.get_address() & (sizeof(bussize_t) - 1);
    short_t bit_shift = byte_shift * 8;
    addr_t busAddr = trans.get_address();

    // check that length is power of two
    sc_assert((totalLen & (totalLen - 1)) == 0);
    sc_assert(beats);

    if (trans.get_address() & (accessLen - 1)) {
      printf("TLM2TL: Unaligned access!");
      trans.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);

      c.a_corrupt = true;
      wait(clock.posedge_event());
      c.a_corrupt = false;
      return;
    }

    c.a_size = log2Size;
    c.a_address = busAddr;
    c.a_mask = mask << byte_shift;

    bool aAcked = true, dAcked = true;

    // Beat 0 - n
    // READ:  n beat from c.d_data => to ack the transaction:
    //  n * c.d_ready & 1 * c.d_valid + n * c.a_valid & 1 * c.a_ready
    // WRITE: n beat from c.a_data => to ack the transaction:
    //  n * c.a_valid & 1 * c.a_ready + 1 * c.d_ready & n * c.d_valid
    c.a_valid = 1;
    if (cmd == tlm::TLM_READ_COMMAND) {
      c.a_opcode = TILELINK_OPCODE_AB_GET;
      c.d_ready = 1;
      aAcked = c.a_ready;
    } else {
      c.a_opcode = TILELINK_OPCODE_AB_PUT_FULL_DATA;
      if (beats == 0) { // Ack on last beat
        c.d_ready = 1;
        dAcked = c.d_ready;
      } else {
        c.d_ready = 0;
        dAcked = false;
      }
    }

    for (unsigned i = 0; i < beats; ++i) {
      bool lastBeat = i == (beats - 1);

      if (cmd == tlm::TLM_READ_COMMAND) {
        wait(clock.posedge_event());
        if (c.a_ready && c.a_valid) {
          c.a_valid = 0;
          aAcked = true;
        }

        sc_assert(c.d_ready);
        while (!c.d_valid) {
          wait(clock.posedge_event());
          if (c.a_ready) {
            aAcked = true;
            c.a_valid = 0;
          }
        }

        sc_assert(c.d_ready &&
                  (c.d_opcode == TILELINK_OPCODE_CD_ACCESS_ACK_DATA));
        setData(data_ptr, accessLen, c.d_data.read(), bit_shift);
      } else {              // TLM_WRITE_COMMAND
        sc_assert(!dAcked); // We ack on the last beat

        if (lastBeat) {
          c.d_ready = 1;
          dAcked = c.d_valid;
        }

        c.a_data = getData(data_ptr, accessLen, bit_shift);
        wait(clock.posedge_event());

        sc_assert(c.a_valid);
        while (!c.a_ready) {
          dAcked |= c.d_ready && c.d_valid;
          wait(clock.posedge_event());
        };

        dAcked |= c.d_ready && c.d_valid;
        if (dAcked)
          sc_assert(c.d_opcode == TILELINK_OPCODE_CD_ACCESS_ACK);
      }

      data_ptr += sizeof(bussize_t);
    }

    if (cmd == tlm::TLM_READ_COMMAND) {
      c.d_ready = 0;
      while (!aAcked) {
        wait(clock.posedge_event());
        sc_assert(c.a_valid == 1);
        if (c.a_ready) {
          aAcked = true;
          sc_assert(c.d_opcode == TILELINK_OPCODE_CD_ACCESS_ACK_DATA);
        }
      }
      c.a_valid = 0;
    } else {
      c.a_valid = 0;
      while (!dAcked) {
        wait(clock.posedge_event());
        sc_assert(c.d_ready == 1);
        if (c.d_valid) {
          dAcked = true;
          sc_assert(c.d_opcode == TILELINK_OPCODE_CD_ACCESS_ACK);
        }
      }
      c.d_ready = 0;
    }

    sc_assert(aAcked && dAcked);

    trans.set_response_status(tlm::TLM_OK_RESPONSE);
    wait(clock.posedge_event());
  }

private:
  // TODO: Improve these functions
  static bussize_t getData(uint8_t * ptr, unsigned len, unsigned bit_shift) {
    sc_assert(sizeof(bussize_t) <= sizeof(uint64_t) &&
              sizeof(bussize_t) >= len);
    if (len == sizeof(bussize_t))
      sc_assert(bit_shift == 0);

    uint64_t r;
    switch (len) {
    case 8:
      r = *((uint64_t *)ptr);
      break;
    case 4:
      r = *((uint32_t *)ptr);
      break;
    case 2:
      r = *((uint16_t *)ptr);
      break;
    case 1:
      r = *((uint8_t *)ptr);
      break;
    default:
      sc_assert(false);
    }

    if (rocketChipQuirk) {
      for (unsigned i = len; i < sizeof(bussize_t); i <<= 1) {
        sc_assert(i * 2 <= sizeof(bussize_t));
        r = r | r << (i * 8);
      }
    } else {
      r <<= bit_shift;
    }
    return r;
  }

  static void setData(uint8_t * ptr, unsigned len, bussize_t val,
                      unsigned bit_shift) {
    sc_assert(sizeof(bussize_t) <= sizeof(uint64_t) &&
              sizeof(bussize_t) >= len);
    if (len == sizeof(bussize_t))
      sc_assert(bit_shift == 0);

    switch (len) {
    case 8:
      *((uint64_t *)ptr) = val;
      return;
    case 4:
      *((uint32_t *)ptr) = val >> bit_shift;
      return;
    case 2:
      *((uint16_t *)ptr) = val >> bit_shift;
      return;
    case 1:
      *((uint8_t *)ptr) = val >> bit_shift;
      return;
    }
    sc_assert(false);
    return;
  }
};

#endif
