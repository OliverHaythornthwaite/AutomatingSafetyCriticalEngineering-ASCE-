#ifndef DCDS_C2_STUB_H
#define DCDS_C2_STUB_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    DCDS_C2_IDLE = 0,
    DCDS_C2_ARMED = 1,
    DCDS_C2_SENT = 2,
    DCDS_C2_ACCEPTED = 3,
    DCDS_C2_FAILED = 4
} dcds_c2_state_t;

typedef enum {
    DCDS_C2_GREEN = 0,
    DCDS_C2_RED = 1
} dcds_c2_colour_t;

typedef struct {
    int link;
    int authority;
    int vehicle_mode;
    bool tile_pressed;
    bool confirm;
    bool ack_positive;
    uint32_t ack_transaction_id;
    uint32_t dt;
    bool reset;
    bool restore_pending;
    bool debug_force_send;
    double command_parameter;
    char *command_name;
} dcds_c2_inputs_t;

typedef struct {
    bool send_request;
    uint32_t transaction_id;
    dcds_c2_state_t state;
    dcds_c2_colour_t colour;
    int16_t encoded_parameter;
} dcds_c2_outputs_t;

void dcds_c2_init(bool restore_pending);
void dcds_c2_select(char *command_name, double parameter);
void dcds_c2_on_confirm(void);
void dcds_c2_on_ack(bool positive, uint32_t transaction_id);
void dcds_c2_step(const dcds_c2_inputs_t *inputs, dcds_c2_outputs_t *outputs);
unsigned dcds_c2_get_transport_send_count(void);
void dcds_c2_reset_transport_send_count(void);

#endif
