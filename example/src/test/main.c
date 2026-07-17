#include <stdint.h>

#define PLIC_PRIORITY_BASE      0xc000000UL
#define PLIC_ENABLE_BASE        0xc002000UL
#define PLIC_CONTEXT0_BASE      0xc200000UL

#define UART0_BASE              0x64000000UL
#define UART_TXDATA_FULL        (1u << 31)
#define UART_IE_TXWM            (1u << 0)
#define UART_IP_TXWM            (1u << 0)
#define UART_IRQ                1
#define UART_TXCTRL_TXEN        (1u << 0)
#define UART_TXCTRL_TXCNT(n)    ((uint32_t)(n) << 16)

#define PLIC_NUM_SOURCES        12
#define PLIC_ENABLE_WORDS       ((PLIC_NUM_SOURCES + 31) / 32)

struct plic_priority_regs {
    volatile uint32_t priority[PLIC_NUM_SOURCES + 1];
} __attribute__((packed));
struct plic_priority_regs *const plic_priority = (struct plic_priority_regs *)PLIC_PRIORITY_BASE;

struct plic_enable_regs {
    volatile uint32_t enable[PLIC_ENABLE_WORDS];
} __attribute__((packed));
struct plic_enable_regs *const plic_enable_regs = (struct plic_enable_regs *)PLIC_ENABLE_BASE;

struct plic_context_regs {
    volatile uint32_t threshold;
    volatile uint32_t claim; /* claim on read, complete on write */
} __attribute__((packed));
struct plic_context_regs *const plic_ctx = (struct plic_context_regs *)PLIC_CONTEXT0_BASE;

struct uart_regs {
    volatile uint32_t tx;
    volatile uint32_t rx;
    volatile uint32_t txctrl;
    volatile uint32_t rxctrl;
    volatile uint32_t ie;
    volatile uint32_t ip;
    volatile uint32_t div;
} __attribute__((packed));
struct uart_regs *const uart0 = (struct uart_regs *)UART0_BASE;

inline void set_mtvec(void (*handler)(void)) {
    asm volatile("csrw mtvec, %0" ::"r"(handler));
}

inline void enable_intr(void) {
    asm volatile("csrs mie, %0" ::"r"(1u << 11));
    asm volatile("csrs mstatus, %0" ::"r"(1u << 3));
}

inline void plic_enable(uint32_t irq) {
    plic_priority->priority[irq] = 1;
    plic_enable_regs->enable[irq / 32] |= (1u << (irq % 32));
    plic_ctx->threshold = 0;
}

inline uint32_t plic_claim(void) {
    return plic_ctx->claim;
}

inline void plic_complete(uint32_t irq) {
    plic_ctx->claim = irq;
}

inline void uart_init(void) {
    uart0->txctrl = 0;
    uart0->div = 867; /* 115200 @ 100MHz */
    uart0->txctrl = UART_TXCTRL_TXEN | UART_TXCTRL_TXCNT(1);
}

inline void uart_putc(char c) {
    while (uart0->tx & UART_TXDATA_FULL)
        ;
    uart0->tx = (uint32_t)c;
}

inline void uart_puts(const char *s) {
    while (*s)
        uart_putc(*s++);
}

inline void uart_enable_tx_irq(void) {
    uart0->ie |= UART_IE_TXWM;
}

inline void uart_disable_tx_irq(void) {
    uart0->ie &= ~UART_IE_TXWM;
}

volatile int uart_tx_irq_seen = 0;

void uart_irq_handler(void) __attribute__((interrupt("machine")));
void uart_irq_handler(void) {
    uint32_t irq = plic_claim();
    if (irq == UART_IRQ) {
        if (uart0->ip & UART_IP_TXWM) {
            uart_tx_irq_seen = 1;
            uart_disable_tx_irq();
        }
    }
    if (irq)
        plic_complete(irq);
}

int main(void) {
    plic_enable(UART_IRQ);
    set_mtvec(uart_irq_handler);
    enable_intr();

    uart_init();

    uart_puts("Hello world - waiting for irq - ");

    uart_enable_tx_irq();
    while (!uart_tx_irq_seen)
        ;

    uart_puts("Done\n");

    // Wait for print to finish
    while (!(uart0->ip & UART_IP_TXWM))
        ;
    return 0;
}
