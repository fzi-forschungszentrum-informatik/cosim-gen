#ifndef TL2TLMBRIDGE_H__
#define TL2TLMBRIDGE_H__

#include "tilelink.h"
#include <systemc>
#include <tlm_utils/simple_initiator_socket.h>

template <typename bussize_t = uint64_t, typename addr_t = uint32_t,
          typename maskType_t = uint8_t, typename short_t = uint8_t,
          typename logSize_t = uint8_t, typename source_t = uint8_t,
          typename sink_t = uint8_t, int tlmMaxSize = 256,
          bool autoConnect = true>
SC_MODULE(TL2TLMBridge) {
public:
  sc_core::sc_in<bool> clock{"clock"};
  sc_core::sc_in<bool> reset{"reset"};
  tlm_utils::simple_initiator_socket<TL2TLMBridge> socket;

  struct TLInConnection<bussize_t, addr_t, maskType_t, short_t, logSize_t,
                        source_t, sink_t>
      c;
  TLSignals<bussize_t, addr_t, maskType_t, short_t, logSize_t, source_t, sink_t>
      signals;

  TL2TLMBridge(sc_core::sc_module_name name)
      : sc_core::sc_module(name), socket("socket"), signals("signals") {
    SC_HAS_PROCESS(TL2TLMBridge);
    SC_THREAD(processReq);
    tlm_gp.set_data_ptr((unsigned char *)databuf);
    if (autoConnect)
      c.connect(signals);
  }

  TL2TLMBridge(sc_core::sc_module_name name, sc_core::sc_clock & clk,
               sc_core::sc_signal<bool> & rst)
      : TL2TLMBridge(name) {
    clock(clk);
    reset(rst);
  }

  void processReq(void) {
    while (true) {
      c.d_valid = false;
      c.a_ready = true;

      if (!clock)
        wait(clock.posedge_event());

      if (!c.a_valid) {
        wait(c.a_valid.posedge_event());
        wait(clock.posedge_event());
      } else if (!c.a_ready) {
        wait(clock.posedge_event());
      }

      sc_assert(!reset);

      addr_t address = c.a_address.read();
      short_t a_opcode = c.a_opcode.read();
      short_t log2size = c.a_size.read();

      c.d_size = log2size;
      unsigned bytes = (1U << log2size);
      unsigned beats = (bytes + sizeof(bussize_t) - 1) / sizeof(bussize_t);

      sc_assert(bytes <= sizeof(databuf));
      sc_assert(c.a_mask != 0);

      short_t byte_shift = 0;
      if (beats == 1) {
        uint64_t shifted_mask = c.a_mask;

        while (!(shifted_mask & 0x1)) {
          shifted_mask >>= 1;
          byte_shift++;
        }
        sc_assert((shifted_mask & (shifted_mask + 1)) == 0 &&
                  "Uncontiguous masks are not supported");

        unsigned checkSize = (int)log2(shifted_mask + 1);

        if (a_opcode == TILELINK_OPCODE_AB_PUT_PARTIAL_DATA) {
          sc_assert(beats == 1);
          sc_assert(checkSize <= bytes);

          if (checkSize < bytes)
            bytes = checkSize;
        } else {
          sc_assert(checkSize == bytes);
        }
      } else {
        sc_assert(c.a_mask == (1UL << sizeof(bussize_t)) - 1);
      }
      short_t bit_shift = byte_shift * 8;

      tlm_gp.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);

      if (a_opcode == TILELINK_OPCODE_AB_GET) {
        c.a_ready = false;
        wait(clock.posedge_event());

        tlm_gp.set_command(tlm::TLM_READ_COMMAND);

        // Read the whole bussize word
        tlm_gp.set_address(address & ~((addr_t)(sizeof(bussize_t) - 1)));
        tlm_gp.set_data_length(bytes < sizeof(bussize_t) ? sizeof(bussize_t)
                                                         : bytes);
        tlm_gp.set_streaming_width(tlm_gp.get_data_length());

        sc_core::sc_time delay(sc_core::SC_ZERO_TIME);
        socket->b_transport(tlm_gp, delay);
        sc_assert(tlm_gp.get_response_status() == tlm::TLM_OK_RESPONSE);

        c.d_opcode = TILELINK_OPCODE_CD_ACCESS_ACK_DATA;
        c.d_valid = true;

        for (unsigned i = 0; i < beats; ++i) {
          c.d_data = databuf[i];

          do {
            wait(clock.posedge_event());
          } while (!c.d_ready);
        }

        c.d_valid = false;

      } else if (a_opcode == TILELINK_OPCODE_AB_PUT_FULL_DATA) {
        c.d_opcode = TILELINK_OPCODE_CD_ACCESS_ACK;
        c.d_valid = true;

        for (unsigned i = 0; i < beats; ++i) {
          while (!c.a_valid) {
            wait(clock.posedge_event());
            if (c.d_ready)
              c.d_valid = false;
          };

          databuf[i] = c.a_data >> bit_shift;
          wait(clock.posedge_event());
          if (c.d_ready)
            c.d_valid = false;
        }

        if (c.d_valid) {
          /* Not acked */
          c.a_ready = false;
          while (!c.d_ready) {
            wait(clock.posedge_event());
          };
          c.d_valid = false;
          wait(clock.posedge_event());
        }

        c.d_valid = false;
        c.a_ready = false;
        wait(clock.posedge_event());

        tlm_gp.set_command(tlm::TLM_WRITE_COMMAND);
        tlm_gp.set_address(address);
        tlm_gp.set_data_length(bytes);
        tlm_gp.set_streaming_width(bytes);
        sc_core::sc_time delay(sc_core::SC_ZERO_TIME);
        socket->b_transport(tlm_gp, delay);
        sc_assert(tlm_gp.get_response_status() == tlm::TLM_OK_RESPONSE);

      } else if (a_opcode == TILELINK_OPCODE_AB_PUT_PARTIAL_DATA) {
        c.d_opcode = TILELINK_OPCODE_CD_ACCESS_ACK;
        c.d_valid = true;
        databuf[0] = c.a_data >> bit_shift;
        do {
          wait(clock.posedge_event());
          c.a_ready = false;
        } while (!c.d_ready);

        c.d_valid = false;
        c.a_ready = false;
        wait(clock.posedge_event());

        tlm_gp.set_command(tlm::TLM_WRITE_COMMAND);
        tlm_gp.set_address(address + byte_shift);
        tlm_gp.set_data_length(bytes);
        tlm_gp.set_streaming_width(bytes);
        sc_core::sc_time delay(sc_core::SC_ZERO_TIME);
        socket->b_transport(tlm_gp, delay);
        sc_assert(tlm_gp.get_response_status() == tlm::TLM_OK_RESPONSE);
      } else {
        sc_assert(false);
      }
    }
  }

private:
  tlm::tlm_generic_payload tlm_gp;
  bussize_t databuf[tlmMaxSize / sizeof(bussize_t)];
};

#endif
