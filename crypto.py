from math import ceil
from struct import Struct

class DispersyCrypto(object):

    def get_security_levels(self):
        raise NotImplementedError()

    def generate_key(self, securitylevel):
        raise NotImplementedError()

    def key_to_public_bin(self, key):
        raise NotImplementedError()

    def key_from_public_bin(self, string):
        raise NotImplementedError()

    def key_to_private_bin(self, key):
        raise NotImplementedError()

    def key_from_private_bin(self, string):
        raise NotImplementedError()

    def is_valid_public_bin(self, string):
        raise NotImplementedError()

    def is_valid_private_bin(self, string):
        raise NotImplementedError()

    def is_valid_signature(self, key, string, signature):
        raise NotImplementedError()

    def create_signature(self, key, string):
        raise NotImplementedError()

    def get_signature_length(self, key):
        raise NotImplementedError()

class ECCrypto(DispersyCrypto):
    """
    The crypto module provides a layer between Dispersy and low level crypographic features.
    
    @author: Boudewijn Schoon
    @organization: Technical University Delft
    @contact: dispersy@frayja.com
    """

    def __init__(self):
        from M2Crypto import EC, BIO

        self._STRUCT_L = Struct(">L")

        # Allow all available curves.
        # Niels: 16-12-2013, if it starts with NID_
        self._CURVES = dict((unicode(curve), getattr(EC, curve)) for curve in dir(EC) if curve.startswith("NID_"))

        # We want to provide a few default curves.  We will change these curves as new become available and
        # old ones to small to provide sufficient security.
        self._CURVES.update({u"very-low": EC.NID_sect163k1,
                        u"low": EC.NID_sect233k1,
                        u"medium": EC.NID_sect409k1,
                        u"high": EC.NID_sect571r1})

    def _progress(*args):
        "Called when no feedback needs to be given."
        pass

    def get_security_levels(self):
        """
        Returns the names of all available curves.
        @rtype: [unicode]
        """
        return _CURVES.keys()

    def generate_key(self, security):
        """
        Generate a new Elliptic Curve object with a new public / private key pair.
    
        Security can be u'low', u'medium', or u'high' depending on how secure you need your Elliptic
        Curve to be.  Currently these values translate into:
            - very-low: NID_sect163k1  ~42 byte signatures
            - low:      NID_sect233k1  ~60 byte signatures
            - medium:   NID_sect409k1 ~104 byte signatures
            - high:     NID_sect571r1 ~144 byte signatures
    
        Besides these predefined curves, all other curves provided by M2Crypto are also available.  For
        a full list of available curves, see ec_get_curves().
    
        @param security: Level of security {u'very-low', u'low', u'medium', or u'high'}.
        @type security: unicode
    
        @note that the NID must always be 160 bits or more, otherwise it will not be able to sign a sha1
            digest.
        """
        assert isinstance(security, unicode)
        assert security in _CURVES
        ec = EC.gen_params(_CURVES[security])
        ec.gen_key()
        return ec

    def key_public_pem_to_public_bin(self, pem):
        "Convert a public key in PEM format into a public key in binary format."
        return "".join(pem.split("\n")[1:-2]).decode("BASE64")

    def key_private_pem_to_private_bin(self, pem):
        """
        Convert a private key in PEM format into a private key in binary format.
    
        @note: Enrcypted pem's are NOT supported and will silently fail.
        """
        return "".join(pem.split("\n")[1:-2]).decode("BASE64")

    def key_to_private_pem(self, ec, cipher=None, password=None):
        "Get the private key in PEM format."
        def get_password(*args):
            return password or ""
        bio = BIO.MemoryBuffer()
        ec.save_key_bio(bio, cipher, get_password)
        return bio.read_all()

    def key_to_public_pem(self, ec):
        "Get the public key in PEM format."
        bio = BIO.MemoryBuffer()
        ec.save_pub_key_bio(bio)
        return bio.read_all()

    def key_from_private_pem(self, pem, password=None):
        "Get the EC from a private PEM."
        def get_password(*args):
            return password or ""
        return EC.load_key_bio(BIO.MemoryBuffer(pem), get_password)

    def key_from_public_pem(self, pem):
        "Get the EC from a public PEM."
        return EC.load_pub_key_bio(BIO.MemoryBuffer(pem))

    def key_check_private_pem(self, pem):
        "Returns True if the input is a valid private key"
        try:
            ec_from_private_pem(pem)
        except:
            return False
        return True

    def key_check_public_pem(self, pem):
        "Returns True if the input is a valid public key"
        try:
            ec_from_public_pem(pem)
        except:
            return False
        return True

    def key_to_private_bin(self, ec):
        "Get the private key in binary format."
        return self.key_private_pem_to_private_bin(self.key_to_private_pem(ec))

    def key_to_public_bin(self, ec):
        "Get the public key in binary format."
        return self.key_public_pem_to_public_bin(self.key_to_public_pem(ec))

    def is_valid_private_bin(self, string):
        "Returns True if the input is a valid private key"
        try:
            self.key_from_private_bin(string)
        except:
            return False
        return True

    def is_valid_public_bin(self, string):
        "Returns True if the input is a valid public key"
        try:
            self.key_from_public_bin(string)
        except:
            return False
        return True

    def key_from_private_bin(self, string):
        "Get the EC from a private key in binary format."
        return self.key_from_private_pem("".join(("-----BEGIN EC PRIVATE KEY-----\n",
                                            string.encode("BASE64"),
                                            "-----END EC PRIVATE KEY-----\n")))

    def key_from_public_bin(self, string):
        "Get the EC from a public key in binary format."
        return self.key_from_public_pem("".join(("-----BEGIN PUBLIC KEY-----\n",
                                           string.encode("BASE64"),
                                           "-----END PUBLIC KEY-----\n")))

    def get_signature_length(self, ec):
        """
        Returns the length, in bytes, of each signature made using EC.
        """
        return int(ceil(len(ec) / 8.0)) * 2

    def create_signature(self, ec, digest):
        """
        Returns the signature of DIGEST made using EC.
        """
        assert isinstance(digest, str), type(digest)
        length = int(ceil(len(ec) / 8.0))

        mpi_r, mpi_s = ec.sign_dsa(digest)
        length_r, = self._STRUCT_L.unpack_from(mpi_r)
        r = mpi_r[-min(length, length_r):]
        length_s, = self._STRUCT_L.unpack_from(mpi_s)
        s = mpi_s[-min(length, length_s):]

        return "".join(("\x00" * (length - len(r)), r, "\x00" * (length - len(s)), s))

    def is_valid_signature(self, ec, digest, signature):
        """
        Returns True when SIGNATURE matches the DIGEST made using EC.
        """
        assert isinstance(digest, str), type(digest)
        assert isinstance(signature, str), type(signature)
        assert len(signature) == ec_signature_length(ec), [len(signature), ec_signature_length(ec)]
        length = len(signature) / 2
        try:
            r = signature[:length]
            # remove all "\x00" prefixes
            while r and r[0] == "\x00":
                r = r[1:]
            # prepend "\x00" when the most significant bit is set
            if ord(r[0]) & 128:
                r = "\x00" + r

            s = signature[length:]
            # remove all "\x00" prefixes
            while s and s[0] == "\x00":
                s = s[1:]
            # prepend "\x00" when the most significant bit is set
            if ord(s[0]) & 128:
                s = "\x00" + s

            mpi_r = _STRUCT_L.pack(len(r)) + r
            mpi_s = _STRUCT_L.pack(len(s)) + s

            # mpi_r3 = bn_to_mpi(bin_to_bn(signature[:length]))
            # mpi_s3 = bn_to_mpi(bin_to_bn(signature[length:]))

            # if not mpi_r == mpi_r3:
            #     raise RuntimeError([mpi_r.encode("HEX"), mpi_r3.encode("HEX")])
            # if not mpi_s == mpi_s3:
            #     raise RuntimeError([mpi_s.encode("HEX"), mpi_s3.encode("HEX")])

            return bool(ec.verify_dsa(digest, mpi_r, mpi_s))

        except:
            return False
