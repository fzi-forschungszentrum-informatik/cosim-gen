#ifndef _ARC_SC_WRAPPER_H
#define _ARC_SC_WRAPPER_H

#include <cstdint>
#include <fstream>
#include <memory>
#include <optional>
#include <systemc>
#include <vector>

template <typename T, typename T_ValueChangeDump>
class ArcSystemCWrapper : sc_core::sc_module {
public:
  typedef ArcSystemCWrapper SC_CURRENT_USER_MODULE;

  ArcSystemCWrapper(sc_core::sc_module_name name, bool trace)
      : sc_core::sc_module(name), arc_model() {
    SC_THREAD(eval);

    trace_enabled = trace;

    if (trace_enabled)
      vcd_start("arcilator.vcd");
  };

  virtual ~ArcSystemCWrapper(){};

  void end_of_elaboration() override {
    for (size_t i = 0; i < numClocks(); ++i) {
      clock_events |= clockPort(i).value_changed_event();
      clock_slots.push_back(clockSlot(i));
    }
  };

  void eval() {
    while (true) {
      sc_core::wait(clock_events);
      mirrorClocks();

      arc_set_io();
      arc_model.eval();
      arc_set_io();
      arc_model.eval();

      if (trace_enabled)
        vcd_dump(sc_core::sc_time_stamp().to_double());
    }
  };

protected:
  T arc_model;
  std::unique_ptr<T_ValueChangeDump> model_vcd;

  sc_core::sc_event_or_list clock_events;
  std::vector<uint8_t *> clock_slots;

  std::ofstream vcd_stream;
  bool trace_enabled;

  void mirrorClocks() {
    for (size_t i = 0; i < clock_slots.size(); ++i)
      *clock_slots[i] = clockPort(i).read() ? 1 : 0;
  };

  virtual size_t numClocks() const = 0;

  virtual const sc_core::sc_in<bool> &clockPort(size_t i) const = 0;

  // Direct pointer into arc_model's view, not a virtual setClock() call per
  // clock per wake - cached once in end_of_elaboration().
  virtual uint8_t *clockSlot(size_t i) = 0;

  virtual void arc_set_io() {
    writeOutputs();
    wait(sc_core::SC_ZERO_TIME); /* Wait for all signals to be stable */
    readInputs();
  };

  void vcd_start(const char *outputFile) {
    vcd_stream.open(outputFile);
    model_vcd.reset(new T_ValueChangeDump(arc_model.vcd(vcd_stream)));
  };

  void vcd_dump(size_t cycle) {
    if (model_vcd) {
      model_vcd->time = cycle;
      model_vcd->writeTimestep(0);
    }
  };

  virtual void readInputs() = 0;

  virtual void writeOutputs() = 0;
};

#endif // guard
