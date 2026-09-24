from src.serial_io.packet_parser import PacketParser, xor_crc_ascii


def test_packet_parser_valid():
    payload = "$CP,100,50000,48000,0.01,0.02,1.00,0.1,0.2,0.3,32.5,450,100,0"
    line = payload + f",{xor_crc_ascii(payload):02X}"
    s = PacketParser().parse(line)
    assert s.ms == 100
    assert s.ir == 50000
    assert abs(s.temp_c - 32.5) < 1e-6
