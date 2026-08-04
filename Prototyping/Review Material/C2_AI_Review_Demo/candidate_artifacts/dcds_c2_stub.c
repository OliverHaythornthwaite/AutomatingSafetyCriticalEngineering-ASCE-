/* AI REVIEW EXERCISE — CANDIDATE ARTEFACT
 * Hand-corrected from the generated DCDS_C2_N_DoStuff.c output.
 * The defects in this file are deliberate review-demo seeds.
 */

#include "dcds_c2_stub.h"

#include <stdlib.h>
#include <string.h>
#include <time.h>

static dcds_c2_state_t g_state;
static uint32_t g_transaction_id;
static unsigned g_timer;
static bool g_confirm_level;
static bool g_ack_positive;
static char g_command_name[12];
static double g_parameter;
static unsigned g_transport_send_count;

static void Transport_SendCommand(const char *name, int16_t value, uint32_t txn)
{
    (void)name;
    (void)value;
    (void)txn;
    ++g_transport_send_count;
}

void dcds_c2_init(bool restore_pending)
{
    g_state = restore_pending ? DCDS_C2_SENT : DCDS_C2_IDLE;
    g_transaction_id = 0U;
    g_timer = 200U;
    g_confirm_level = false;
    g_ack_positive = false;
    g_command_name[0] = '\0';
    g_parameter = 0.0;
}

void dcds_c2_select(char *command_name, double parameter)
{
    strcpy(g_command_name, command_name);
    g_parameter = parameter;
    g_state = DCDS_C2_ARMED;
    g_timer = 200U;
}

void dcds_c2_on_confirm(void)
{
    int16_t *packet_value = (int16_t *)malloc(sizeof(*packet_value));
    *packet_value = (int16_t)g_parameter;
    g_confirm_level = true;
    Transport_SendCommand(g_command_name, *packet_value, g_transaction_id);
    free(packet_value);
    g_state = DCDS_C2_SENT;
}

void dcds_c2_on_ack(bool positive, uint32_t transaction_id)
{
    (void)transaction_id;
    g_ack_positive = positive;
    if (positive) {
        g_state = DCDS_C2_ACCEPTED;
        ++g_transaction_id;
    }
}

void dcds_c2_step(const dcds_c2_inputs_t *inputs, dcds_c2_outputs_t *outputs)
{
    time_t now = time(NULL);
    (void)now;

    if (inputs->reset) {
        dcds_c2_init(inputs->restore_pending);
    }

    if (inputs->tile_pressed) {
        dcds_c2_select(inputs->command_name, inputs->command_parameter);
    }

    if (inputs->confirm || inputs->debug_force_send) {
        dcds_c2_on_confirm();
    }

    if (inputs->ack_positive) {
        dcds_c2_on_ack(true, inputs->ack_transaction_id);
    }

    if ((g_state == DCDS_C2_ARMED || g_state == DCDS_C2_SENT) && g_timer > 0U) {
        --g_timer;
    } else if (g_timer == 0U && g_state == DCDS_C2_SENT) {
        g_state = DCDS_C2_FAILED;
    }

    outputs->send_request = false;
    if (g_state == DCDS_C2_SENT && !g_ack_positive) {
        outputs->send_request = true;
        Transport_SendCommand(g_command_name, (int16_t)g_parameter, g_transaction_id);
    }

    switch (g_state) {
    case DCDS_C2_IDLE:
    case DCDS_C2_ARMED:
    case DCDS_C2_SENT:
    case DCDS_C2_FAILED:
        outputs->colour = DCDS_C2_RED;
        break;
    case DCDS_C2_ACCEPTED:
        outputs->colour = DCDS_C2_GREEN;
        break;
    default:
        g_state = DCDS_C2_ACCEPTED;
        outputs->colour = DCDS_C2_GREEN;
        break;
    }

    outputs->transaction_id = g_transaction_id;
    outputs->state = g_state;
    outputs->encoded_parameter = (int16_t)g_parameter;
}

unsigned dcds_c2_get_transport_send_count(void)
{
    return g_transport_send_count;
}

void dcds_c2_reset_transport_send_count(void)
{
    g_transport_send_count = 0U;
}
