from os import environ, getcwd, path
from socket import getfqdn
from subprocess import Popen, PIPE, STDOUT
from threading import Thread
from time import time, sleep
from unittest import skip, skipUnless

from ..bootstrap import Bootstrap
from ..candidate import BootstrapCandidate
from ..logger import get_logger
from ..message import Message, DropMessage
from .debugcommunity.community import DebugCommunity
from .dispersytestclass import DispersyTestFunc


logger = get_logger(__name__)
summary = get_logger("test-bootstrap-summary")


class TestBootstrapServers(DispersyTestFunc):

    def test_tracker(self):
        """
        Runs tracker.py and connects to it.
        """

        Bootstrap.enable = True
        tracker_file = "dispersy/tool/tracker.py"
        tracker_path = getcwd()
        while tracker_path:
            logger.debug("looking for %s in %s", tracker_file, tracker_path)
            if path.isfile(path.join(tracker_path, tracker_file)):
                break
            tracker_path = path.dirname(tracker_path)
        logger.debug("using tracker cwd \"%s\"", tracker_path)

        tracker_address = (self._dispersy.wan_address[0], 14242)
        args = ["python",
                "-c", "from dispersy.tool.tracker import main; main()",
                "--statedir", ".",
                "--port", str(tracker_address[1]),
                "--log-identifier", "tracker"]
        logger.debug("start tracker %s", args)

        def logstream(stream, loggercb):
            while True:
                out = stream.readline()
                if out:
                    loggercb(out.rstrip())
                else:
                    break
        tracker = Popen(args, cwd=tracker_path, stdout=PIPE, stderr=STDOUT)
        tracker_logging_thread = Thread(name="TrackerLoggingThread", target=logstream, args=(tracker.stdout, lambda s: logger.info("tracker is printing: " + s)))
        tracker_logging_thread.start()

        # can take a few seconds to start on older machines (or when running on a remote file
        # system)
        sleep(5)

        try:
            class Community(DebugCommunity):
                @property
                def dispersy_enable_candidate_walker(self):
                    return False
                @property
                def dispersy_enable_candidate_walker_responses(self):
                    return True

            node, = self.create_nodes(1, communityclass=Community)

            # node sends introduction request
            destination = BootstrapCandidate(tracker_address, False)
            node.send_message(node.create_introduction_request(destination=destination,
                                                                        source_lan = node.lan_address,
                                                                        source_wan = node.wan_address,
                                                                        advice = True,
                                                                        connection_type = u"unknown",
                                                                        sync = None,
                                                                        identifier = 4242,
                                                                        global_time = 42),
                              destination)

            # node receives missing identity
            _, message = node.receive_message(names=[u"dispersy-missing-identity"]).next()
            self.assertEqual(message.payload.mid, node.my_member.mid)

            packet = node.fetch_packets([u"dispersy-identity", ], node.my_member.mid)[0]
            node.send_packet(packet,  destination)

            node.process_packets()

            _, message = node.receive_message(names=[u"dispersy-identity"]).next()

        finally:
            logger.debug("terminate tracker")

            tracker.terminate()  # sends SIGTERM
            self.assertEqual(tracker.wait(), 0), tracker.returncode

    @skipUnless(environ.get("TEST_BOOTSTRAP") == "yes", "This 'unittest' tests the external bootstrap processes, as such, this is not part of the code review process")
    def test_servers_are_up(self):
        """
        Sends a dispersy-introduction-request to the trackers and counts how long it takes until the
        dispersy-introduction-response is received.
        """
        class PingCommunity(DebugCommunity):

            def __init__(self, *args, **kargs):
                super(PingCommunity, self).__init__(*args, **kargs)

                self._pings_done = 0
                self._request = {}
                self._summary = {}
                self._hostname = {}
                self._identifiers = {}
                self._pcandidates = self._dispersy._bootstrap_candidates.values()
                # self._pcandidates = [BootstrapCandidate(("130.161.211.198", 6431))]

                for candidate in self._pcandidates:
                    self._request[candidate.sock_addr] = {}
                    self._summary[candidate.sock_addr] = []
                    self._hostname[candidate.sock_addr] = getfqdn(candidate.sock_addr[0])
                    self._identifiers[candidate.sock_addr] = ""

            def _initialize_meta_messages(self):
                super(PingCommunity, self)._initialize_meta_messages()

            @property
            def dispersy_enable_candidate_walker(self):
                return False

            @property
            def dispersy_enable_candidate_walker_responses(self):
                return True

            def take_step(self, allow_sync):
                test.fail("we disabled the walker")

            def on_introduction_response(self, messages):
                now = time()
                logger.debug("PONG")
                for message in messages:
                    candidate = message.candidate
                    if candidate.sock_addr in self._request:
                        request_stamp = self._request[candidate.sock_addr].pop(message.payload.identifier, 0.0)
                        self._summary[candidate.sock_addr].append(now - request_stamp)
                        self._identifiers[candidate.sock_addr] = message.authentication.member.mid
                return super(DebugCommunity, self).on_introduction_response(messages)

            def ping(self, now):
                logger.debug("PING")
                self._pings_done += 1
                for candidate in self._pcandidates:
                    request = self.create_introduction_request(candidate, False)
                    self._request[candidate.sock_addr][request.payload.identifier] = now

            def summary(self):
                for sock_addr, rtts in sorted(self._summary.iteritems()):
                    if rtts:
                        summary.info("%s %15s:%-5d %-30s %dx %.1f avg  [%s]",
                                     self._identifiers[sock_addr].encode("HEX"),
                                     sock_addr[0],
                                     sock_addr[1],
                                     self._hostname[sock_addr],
                                     len(rtts),
                                     sum(rtts) / len(rtts),
                                     ", ".join(str(round(rtt, 1)) for rtt in rtts[-10:]))
                    else:
                        summary.warning("%s:%d %s missing", sock_addr[0], sock_addr[1], self._hostname[sock_addr])

            def finish(self, request_count, min_response_count, max_rtt):
                # write graph statistics
                handle = open("summary.txt", "w+")
                handle.write("HOST_NAME ADDRESS REQUESTS RESPONSES\n")
                for sock_addr, rtts in self._summary.iteritems():
                    handle.write("%s %s:%d %d %d\n" % (self._hostname[sock_addr], sock_addr[0], sock_addr[1], self._pings_done, len(rtts)))
                handle.close()

                handle = open("walk_rtts.txt", "w+")
                handle.write("HOST_NAME ADDRESS RTT\n")
                for sock_addr, rtts in self._summary.iteritems():
                    for rtt in rtts:
                        handle.write("%s %s:%d %f\n" % (self._hostname[sock_addr], sock_addr[0], sock_addr[1], rtt))
                handle.close()

                for sock_addr, rtts in self._summary.iteritems():
                    test.assertLessEqual(min_response_count, len(rtts), "Only received %d/%d responses from %s:%d" % (len(rtts), request_count, sock_addr[0], sock_addr[1]))
                    test.assertLessEqual(sum(rtts) / len(rtts), max_rtt, "Average RTT %f from %s:%d is more than allowed %f" % (sum(rtts) / len(rtts), sock_addr[0], sock_addr[1], max_rtt))

        community = PingCommunity.create_community(self._dispersy, self._my_member)

        test = self
        PING_COUNT = 10
        ASSERT_MARGIN = 0.9
        MAX_RTT = 0.5
        for _ in xrange(PING_COUNT):
            community.ping(time())
            yield 5.0
            community.summary()

        # cleanup
        community.create_destroy_community(u"hard-kill")
        self._dispersy.get_community(community.cid).unload_community()

        # assert when not all of the servers are responding
        community.finish(PING_COUNT, PING_COUNT * ASSERT_MARGIN, MAX_RTT)

    @skip("The stress test is not actually a unittest")
    def test_perform_heavy_stress_test(self):
        """
        Sends many a dispersy-introduction-request messages to a single tracker and counts how long
        it takes until the dispersy-introduction-response messages are received.
        """
        class PingCommunity(DebugCommunity):

            def __init__(self, master, candidates):
                super(PingCommunity, self).__init__(master)

                self._original_my_member = self._my_member

                self._request = {}
                self._summary = {}
                self._hostname = {}
                self._identifiers = {}
                self._pcandidates = candidates
                self._queue = []
                # self._pcandidates = self._dispersy._bootstrap_candidates.values()
                # self._pcandidates = [BootstrapCandidate(("130.161.211.198", 6431))]

                for candidate in self._pcandidates:
                    self._request[candidate.sock_addr] = {}
                    self._summary[candidate.sock_addr] = []
                    self._hostname[candidate.sock_addr] = getfqdn(candidate.sock_addr[0])
                    self._identifiers[candidate.sock_addr] = ""

            def _initialize_meta_messages(self):
                super(PingCommunity, self)._initialize_meta_messages()

                # replace the callbacks for the dispersy-introduction-response message
                meta = self._meta_messages[u"dispersy-introduction-response"]
                self._meta_messages[meta.name] = Message(meta.community, meta.name, meta.authentication, meta.resolution, meta.distribution, meta.destination, meta.payload, self.check_introduction_response, meta.handle_callback, meta.undo_callback, meta.batch)

            @property
            def dispersy_enable_candidate_walker(self):
                return False

            @property
            def dispersy_enable_candidate_walker_responses(self):
                return True

            def dispersy_take_step(self):
                test.fail("we disabled the walker")

            def create_dispersy_identity(self, sign_with_master=False, store=True, update=True, member=None):
                self._my_member = member if member else self._original_my_member
                try:
                    return super(PingCommunity, self).create_dispersy_identity(sign_with_master, store, update)
                finally:
                    self._my_member = self._original_my_member

            def check_introduction_response(self, messages):
                now = time()
                for message in messages:
                    candidate = message.candidate
                    if candidate.sock_addr in self._request:
                        request_stamp = self._request[candidate.sock_addr].pop(message.payload.identifier, 0.0)
                        if request_stamp:
                            self._summary[candidate.sock_addr].append(now - request_stamp)
                            self._identifiers[candidate.sock_addr] = message.authentication.member.mid
                        else:
                            logger.warning("identifier clash %s", message.payload.identifier)

                    yield DropMessage(message, "not doing anything in this script")

            def prepare_ping(self, member):
                self._my_member = member
                try:
                    for candidate in self._pcandidates:
                        request = self._dispersy.create_introduction_request(self, candidate, False, forward=False)
                        self._queue.append((request.payload.identifier, request.packet, candidate))
                finally:
                    self._my_member = self._original_my_member

            def ping_from_queue(self, count):
                for identifier, packet, candidate in self._queue[:count]:
                    self._dispersy.endpoint.send([candidate], [packet])
                    self._request[candidate.sock_addr][identifier] = time()

                self._queue = self._queue[count:]

            def ping(self, member):
                self._my_member = member
                try:
                    for candidate in self._pcandidates:
                        request = self._dispersy.create_introduction_request(self, candidate, False)
                        self._request[candidate.sock_addr][request.payload.identifier] = time()
                finally:
                    self._my_member = self._original_my_member

            def summary(self):
                for sock_addr, rtts in sorted(self._summary.iteritems()):
                    if rtts:
                        logger.info("%s %15s:%-5d %-30s %dx %.1f avg  [%s]",
                                    self._identifiers[sock_addr].encode("HEX"),
                                    sock_addr[0],
                                    sock_addr[1],
                                    self._hostname[sock_addr],
                                    len(rtts),
                                    sum(rtts) / len(rtts),
                                    ", ".join(str(round(rtt, 1)) for rtt in rtts[-10:]))
                    else:
                        logger.warning("%s:%d %s missing", sock_addr[0], sock_addr[1], self._hostname[sock_addr])

        MEMBERS = 10000  # must be a multiple of 100
        COMMUNITIES = 1
        ROUNDS = 10

        logger.info("prepare communities, members, etc")
        with self._dispersy.database:
            candidates = [BootstrapCandidate(("130.161.211.245", 6429), False)]
            communities = [PingCommunity.create_community(self._dispersy, self._my_member, candidates) for _ in xrange(COMMUNITIES)]
            members = [self._dispersy.get_new_member(u"low") for _ in xrange(MEMBERS)]

            for community in communities:
                for member in members:
                    community.create_dispersy_identity(member=member)

        logger.info("prepare request messages")
        for _ in xrange(ROUNDS):
            for community in communities:
                for member in members:
                    community.prepare_ping(member)

            yield 5.0
        yield 15.0

        logger.info("ping-ping")
        BEGIN = time()
        for _ in xrange(ROUNDS):
            for community in communities:
                for _ in xrange(MEMBERS / 100):
                    community.ping_from_queue(100)
                    yield 0.1

            for community in communities:
                community.summary()
        END = time()

        yield 10.0
        logger.info("--- did %d requests per community", ROUNDS * MEMBERS)
        logger.info("--- spread over %.2f seconds", END - BEGIN)
        for community in communities:
            community.summary()

        # cleanup
        community.create_destroy_community(u"hard-kill")
        self._dispersy.get_community(community.cid).unload_community()
