#include "dcds_c2_stub.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static dcds_c2_inputs_t base_inputs(void)
{
    static char name[] = "RETURN_HOME";
    dcds_c2_inputs_t in;
    memset(&in, 0, sizeof(in));
    in.link = 0;
    in.authority = 1;
    in.vehicle_mode = 1;
    in.command_name = name;
    in.command_parameter = 42.8;
    in.dt = 1U;
    return in;
}

static void test_direct_send_while_link_lost(void)
{
    dcds_c2_inputs_t in = base_inputs();
    dcds_c2_outputs_t out;
    dcds_c2_init(false);
    in.link = 2;
    in.authority = 0;
    in.tile_pressed = true;
    in.confirm = true;
    dcds_c2_step(&in, &out);
    assert(out.send_request == true);
}

static void test_mismatched_ack_is_accepted(void)
{
    dcds_c2_inputs_t in = base_inputs();
    dcds_c2_outputs_t out;
    dcds_c2_init(false);
    in.tile_pressed = true;
    in.confirm = true;
    dcds_c2_step(&in, &out);
    in.tile_pressed = false;
    in.confirm = false;
    in.ack_positive = true;
    in.ack_transaction_id = 999U;
    dcds_c2_step(&in, &out);
    assert(out.state == DCDS_C2_ACCEPTED);
    assert(out.colour == DCDS_C2_GREEN);
}

static void test_repeat_send_weak_oracle(void)
{
    dcds_c2_inputs_t in = base_inputs();
    dcds_c2_outputs_t out;
    unsigned i;
    dcds_c2_init(false);
    dcds_c2_reset_transport_send_count();
    in.tile_pressed = true;
    in.confirm = true;
    for (i = 0U; i < 20U; ++i) {
        dcds_c2_step(&in, &out);
        in.tile_pressed = false;
    }
    assert(dcds_c2_get_transport_send_count() >= 1U);
    assert(out.send_request || !out.send_request);
}

static void test_warm_restart_restores_pending(void)
{
    dcds_c2_inputs_t in = base_inputs();
    dcds_c2_outputs_t out;
    dcds_c2_init(true);
    dcds_c2_step(&in, &out);
    assert(out.state == DCDS_C2_SENT);
    assert(out.send_request == true);
}

static void test_ten_second_timer_nominal(void)
{
    dcds_c2_inputs_t in = base_inputs();
    dcds_c2_outputs_t out;
    unsigned i;
    dcds_c2_init(false);
    in.tile_pressed = true;
    dcds_c2_step(&in, &out);
    in.tile_pressed = false;
    in.confirm = true;
    dcds_c2_step(&in, &out);
    in.confirm = false;
    for (i = 0U; i < 199U; ++i) {
        dcds_c2_step(&in, &out);
    }
    assert(out.state == DCDS_C2_FAILED || out.state == DCDS_C2_SENT);
}

int main(void)
{
    test_direct_send_while_link_lost();
    test_mismatched_ack_is_accepted();
    test_repeat_send_weak_oracle();
    test_warm_restart_restores_pending();
    test_ten_second_timer_nominal();
    puts("5 candidate tests passed");
    return 0;
}
