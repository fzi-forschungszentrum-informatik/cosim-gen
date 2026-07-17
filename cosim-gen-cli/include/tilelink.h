#ifndef TILELINK_H
#define TILELINK_H

#include <systemc>

enum {
  TILELINK_OPCODE_AB_PUT_FULL_DATA = 0,    // -> AccessAck
  TILELINK_OPCODE_AB_PUT_PARTIAL_DATA = 1, // -> AccessAck
  TILELINK_OPCODE_AB_ARITHMETIC_DATA = 2,  // -> AccessAckData
  TILELINK_OPCODE_AB_LOGICAL_DATA = 3,     // -> AccessAckData
  TILELINK_OPCODE_AB_GET = 4,              // -> AccessAckData
  TILELINK_OPCODE_AB_HINT_ACK = 5          // -> HintAck
};

enum {
  TILELINK_OPCODE_CD_ACCESS_ACK = 0,
  TILELINK_OPCODE_CD_ACCESS_ACK_DATA = 1,
  TILELINK_OPCODE_CD_HINT_ACK = 2,
};

template <typename bussize_t = uint64_t, typename addr_t = uint32_t,
          typename maskType_t = uint8_t, typename short_t = uint8_t,
          typename logSize_t = uint8_t, typename source_t = uint8_t,
          typename sink_t = uint8_t>
struct TLSignals {
  sc_core::sc_signal<bool> a_ready;
  sc_core::sc_signal<bool> d_valid;
  sc_core::sc_signal<short_t> d_opcode;
  sc_core::sc_signal<short_t> d_param;
  sc_core::sc_signal<logSize_t> d_size;
  sc_core::sc_signal<source_t> d_source;
  sc_core::sc_signal<sink_t> d_sink;
  sc_core::sc_signal<bool> d_denied;
  sc_core::sc_signal<bussize_t> d_data;
  sc_core::sc_signal<bool> d_corrupt;

  sc_core::sc_signal<bool> a_valid;
  sc_core::sc_signal<short_t> a_opcode;
  sc_core::sc_signal<short_t> a_param;
  sc_core::sc_signal<logSize_t> a_size;
  sc_core::sc_signal<source_t> a_source;
  sc_core::sc_signal<addr_t> a_address;
  sc_core::sc_signal<maskType_t> a_mask;
  sc_core::sc_signal<bussize_t> a_data;
  sc_core::sc_signal<bool> a_corrupt;
  sc_core::sc_signal<bool> d_ready;

  TLSignals(){};
  TLSignals(std::string name_)
      : a_ready((name_ + "_a_ready").c_str()),
        d_valid((name_ + "_d_valid").c_str()),
        d_opcode((name_ + "_d_opcode").c_str()),
        d_param((name_ + "_d_param").c_str()),
        d_size((name_ + "_d_size").c_str()),
        d_source((name_ + "_d_source").c_str()),
        d_sink((name_ + "_d_sink").c_str()),
        d_denied((name_ + "_d_denied").c_str()),
        d_data((name_ + "_d_data").c_str()),
        d_corrupt((name_ + "_d_corrupt").c_str()),
        a_valid((name_ + "_a_valid").c_str()),
        a_opcode((name_ + "_a_opcode").c_str()),
        a_param((name_ + "_a_param").c_str()),
        a_size((name_ + "_a_size").c_str()),
        a_source((name_ + "_a_source").c_str()),
        a_address((name_ + "_a_address").c_str()),
        a_mask((name_ + "_a_mask").c_str()),
        a_data((name_ + "_a_data").c_str()),
        a_corrupt((name_ + "_a_corrupt").c_str()),
        d_ready((name_ + "_d_ready").c_str()){};
};

template <typename bussize_t = uint64_t, typename addr_t = uint32_t,
          typename maskType_t = uint8_t, typename short_t = uint8_t,
          typename logSize_t = uint8_t, typename source_t = uint8_t,
          typename sink_t = uint8_t>
struct TLOutConnection {
  sc_core::sc_out<short_t> a_opcode{"a_opcode"}; // 3 bit
  sc_core::sc_out<short_t> a_param{"a_param"};   // 3 bit -- CURRENTLY UNUSED
  sc_core::sc_out<logSize_t> a_size{"a_size"};   // z: 2^z bytes max transfer
  sc_core::sc_out<source_t> a_source{
      "a_source"}; // o: per-link master source id -- CURRENTLY UNUSED
  sc_core::sc_out<addr_t> a_address{
      "a_address"}; // a: address size (aligned to a_size)
  sc_core::sc_out<maskType_t> a_mask{"a_mask"}; // w: buswidth/8
  sc_core::sc_out<bussize_t> a_data{"a_data"};  // 8w: buswidth
  sc_core::sc_out<bool> a_corrupt{"a_corrupt"}; // CURRENTLY UNUSED
  sc_core::sc_out<bool> a_valid{"a_valid"};
  sc_core::sc_in<bool> a_ready{"a_ready"};

  sc_core::sc_in<short_t> d_opcode{"d_opcode"}; // 3 bit
  sc_core::sc_in<short_t> d_param{
      "d_param"}; // 2 bit (Depends on d_opcode) -- CURRENTLY UNUSED
  sc_core::sc_in<logSize_t> d_size{"d_size"}; // z: 2^z bytes max transfer
  sc_core::sc_in<source_t> d_source{
      "d_source"}; // o: per-link master source id -- CURRENTLY UNUSED
  sc_core::sc_in<sink_t> d_sink{
      "d_sink"}; // i: per-link slave sink id -- CURRENTLY UNUSED
  sc_core::sc_in<bool> d_denied{"d_denied"};
  sc_core::sc_in<bussize_t> d_data{"d_data"}; // 8w: buswidth
  sc_core::sc_in<bool> d_corrupt{"d_corrupt"};
  sc_core::sc_in<bool> d_valid{"d_valid"};
  sc_core::sc_out<bool> d_ready{"d_ready"};

  void connect(TLSignals<bussize_t, addr_t, maskType_t, short_t, logSize_t,
                         source_t, sink_t> &s) {
    a_ready(s.a_ready);
    a_valid(s.a_valid);
    a_opcode(s.a_opcode);
    a_size(s.a_size);
    a_source(s.a_source);
    a_mask(s.a_mask);
    d_ready(s.d_ready);
    d_valid(s.d_valid);
    d_opcode(s.d_opcode);
    d_size(s.d_size);
    d_source(s.d_source);
    a_address(s.a_address);
    a_data(s.a_data);
    d_data(s.d_data);
    a_param(s.a_param);
    a_corrupt(s.a_corrupt);
    d_param(s.d_param);
    d_sink(s.d_sink);
    d_denied(s.d_denied);
    d_corrupt(s.d_corrupt);
  }
};

template <typename bussize_t = uint64_t, typename addr_t = uint32_t,
          typename maskType_t = uint8_t, typename short_t = uint8_t,
          typename logSize_t = uint8_t, typename source_t = uint8_t,
          typename sink_t = uint8_t>
struct TLInConnection {
  sc_core::sc_in<short_t> a_opcode{"a_opcode"}; // 3 bit
  sc_core::sc_in<short_t> a_param{"a_param"};   // 3 bit -- CURRENTLY UNUSED
  sc_core::sc_in<logSize_t> a_size{"a_size"};   // z: 2^z bytes max transfer
  sc_core::sc_in<source_t> a_source{
      "a_source"}; // o: per-link master source id -- CURRENTLY UNUSED
  sc_core::sc_in<addr_t> a_address{
      "a_address"}; // a: address size (aligned to a_size)
  sc_core::sc_in<maskType_t> a_mask{"a_mask"}; // w: buswidth/8
  sc_core::sc_in<bussize_t> a_data{"a_data"};  // 8w: buswidth
  sc_core::sc_in<bool> a_corrupt{"a_corrupt"}; // CURRENTLY UNUSED
  sc_core::sc_in<bool> a_valid{"a_valid"};
  sc_core::sc_out<bool> a_ready{"a_ready"};

  sc_core::sc_out<short_t> d_opcode{"d_opcode"}; // 3 bit
  sc_core::sc_out<short_t> d_param{
      "d_param"}; // 2 bit (Depends on d_opcode) -- CURRENTLY UNUSED
  sc_core::sc_out<logSize_t> d_size{"d_size"}; // z: 2^z bytes max transfer
  sc_core::sc_out<source_t> d_source{
      "d_source"}; // o: per-link master source id -- CURRENTLY UNUSED
  sc_core::sc_out<sink_t> d_sink{
      "d_sink"}; // i: per-link slave sink id -- CURRENTLY UNUSED
  sc_core::sc_out<bool> d_denied{"d_denied"};
  sc_core::sc_out<bussize_t> d_data{"d_data"}; // 8w: buswidth
  sc_core::sc_out<bool> d_corrupt{"d_corrupt"};
  sc_core::sc_out<bool> d_valid{"d_valid"};
  sc_core::sc_in<bool> d_ready{"d_ready"};

  void connect(TLSignals<bussize_t, addr_t, maskType_t, short_t, logSize_t,
                         source_t, sink_t> &s) {
    a_ready(s.a_ready);
    a_valid(s.a_valid);
    a_opcode(s.a_opcode);
    a_size(s.a_size);
    a_source(s.a_source);
    a_mask(s.a_mask);
    d_ready(s.d_ready);
    d_valid(s.d_valid);
    d_opcode(s.d_opcode);
    d_size(s.d_size);
    d_source(s.d_source);
    a_address(s.a_address);
    a_data(s.a_data);
    d_data(s.d_data);
    a_param(s.a_param);
    a_corrupt(s.a_corrupt);
    d_param(s.d_param);
    d_sink(s.d_sink);
    d_denied(s.d_denied);
    d_corrupt(s.d_corrupt);
  }
};

#define TL_ARC_SLAVE_READ(module, prefix, bus)                                 \
  module.prefix##a_valid = bus.a_valid.read();                                 \
  module.prefix##a_bits_opcode = bus.a_opcode.read();                          \
  module.prefix##a_bits_param = bus.a_param.read();                            \
  module.prefix##a_bits_size = bus.a_size.read();                              \
  module.prefix##a_bits_source = bus.a_source.read();                          \
  module.prefix##a_bits_address = bus.a_address.read();                        \
  module.prefix##a_bits_mask = bus.a_mask.read();                              \
  module.prefix##a_bits_data = bus.a_data.read();                              \
  module.prefix##a_bits_corrupt = bus.a_corrupt.read();                        \
  module.prefix##d_ready = bus.d_ready.read();

#define TL_ARC_SLAVE_WRITE(module, prefix, bus)                                \
  bus.a_ready.write(module.prefix##a_ready);                                   \
  bus.d_valid.write(module.prefix##d_valid);                                   \
  bus.d_opcode.write(module.prefix##d_bits_opcode);                            \
  bus.d_param.write(module.prefix##d_bits_param);                              \
  bus.d_size.write(module.prefix##d_bits_size);                                \
  bus.d_source.write(module.prefix##d_bits_source);                            \
  bus.d_sink.write(module.prefix##d_bits_sink);                                \
  bus.d_denied.write(module.prefix##d_bits_denied);                            \
  bus.d_data.write(module.prefix##d_bits_data);                                \
  bus.d_corrupt.write(module.prefix##d_bits_corrupt);

#define TL_ARC_MASTER_READ(module, prefix, bus)                                \
  module.prefix##a_ready = bus.a_ready.read();                                 \
  module.prefix##d_valid = bus.d_valid.read();                                 \
  module.prefix##d_bits_opcode = bus.d_opcode.read();                          \
  module.prefix##d_bits_param = bus.d_param.read();                            \
  module.prefix##d_bits_size = bus.d_size.read();                              \
  module.prefix##d_bits_source = bus.d_source.read();                          \
  module.prefix##d_bits_sink = bus.d_sink.read();                              \
  module.prefix##d_bits_denied = bus.d_denied.read();                          \
  module.prefix##d_bits_data = bus.d_data.read();                              \
  module.prefix##d_bits_corrupt = bus.d_corrupt.read();

#define TL_ARC_MASTER_WRITE(module, prefix, bus)                               \
  bus.a_valid.write(module.prefix##a_valid);                                   \
  bus.a_opcode.write(module.prefix##a_bits_opcode);                            \
  bus.a_param.write(module.prefix##a_bits_param);                              \
  bus.a_size.write(module.prefix##a_bits_size);                                \
  bus.a_source.write(module.prefix##a_bits_source);                            \
  bus.a_address.write(module.prefix##a_bits_address);                          \
  bus.a_mask.write(module.prefix##a_bits_mask);                                \
  bus.a_data.write(module.prefix##a_bits_data);                                \
  bus.a_corrupt.write(module.prefix##a_bits_corrupt);                          \
  bus.d_ready.write(module.prefix##d_ready);

#define TL_VERILATOR_CONNECT(module, prefix, sig)                              \
  module.prefix##a_ready(sig.a_ready);                                         \
  module.prefix##a_valid(sig.a_valid);                                         \
  module.prefix##a_bits_opcode(sig.a_opcode);                                  \
  module.prefix##a_bits_size(sig.a_size);                                      \
  module.prefix##a_bits_source(sig.a_source);                                  \
  module.prefix##a_bits_mask(sig.a_mask);                                      \
  module.prefix##d_ready(sig.d_ready);                                         \
  module.prefix##d_valid(sig.d_valid);                                         \
  module.prefix##d_bits_opcode(sig.d_opcode);                                  \
  module.prefix##d_bits_size(sig.d_size);                                      \
  module.prefix##d_bits_source(sig.d_source);                                  \
  module.prefix##a_bits_address(sig.a_address);                                \
  module.prefix##a_bits_data(sig.a_data);                                      \
  module.prefix##d_bits_data(sig.d_data);                                      \
  module.prefix##a_bits_param(sig.a_param);                                    \
  module.prefix##a_bits_corrupt(sig.a_corrupt);                                \
  module.prefix##d_bits_param(sig.d_param);                                    \
  module.prefix##d_bits_sink(sig.d_sink);                                      \
  module.prefix##d_bits_denied(sig.d_denied);                                  \
  module.prefix##d_bits_corrupt(sig.d_corrupt);

#endif
