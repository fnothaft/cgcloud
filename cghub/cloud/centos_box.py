import re
from distutils.version import LooseVersion

from fabric.operations import run

from box import fabric_task
from cghub.cloud.yum_box import YumBox


ADMIN_USER = 'admin'


class CentosBox(YumBox ):
    """
    A box representing EC2 instances that boots of a RightScale CentOS AMI. Most of the
    complexity in this class stems from a workaround for RightScale's handling of the root
    account. RightScale does not offer a non-root admin account, so after the instance boots for
    the first time, we create an admin account and disable SSH and console logins to the root
    account, just like on Canonical's Ubuntu AMIs. The instance is tagged with the name of the
    admin account such that we can look it up later.
    """

    def release(self):
        """
        :return: the version number of the CentOS release, e.g. "6.4"
        """
        raise NotImplementedError

    def __init__(self, env):
        super( CentosBox, self ).__init__( env )
        self._username = None

    def username(self):
        if self._username is None:
            default_username = 'root' if self.generation == 0 else 'admin'
            self._username = self.get_instance( ).tags.get( 'admin_user', default_username )
        return self._username

    def _set_username(self, admin_user):
        self._username = admin_user
        self.get_instance( ).add_tag( 'admin_user', admin_user )

    def _base_image(self):
        release = self.release( )
        images = self.connection.get_all_images( owners='411009282317',
                                                 filters={
                                                     'name': 'RightImage_CentOS_%s_x64*' % release,
                                                     'root-device-type': 'ebs' } )
        if not images:
            raise RuntimeError( "Can't find any suitable AMIs for CentOS release %s" % release )
        max_version = None
        base_image = None
        for image in images:
            match = re.match( 'RightImage_CentOS_(\d+(?:\.\d+)*)_x64_v(\d+(?:\.\d+)*)_EBS',
                              image.name )
            if match:
                assert match.group( 1 ) == release
                version = LooseVersion( match.group( 2 ) )
                if max_version is None or max_version < version:
                    max_version = version
                    base_image = image
        if not base_image:
            raise RuntimeError( "Can't find AMI matching CentOS %s" % release )
        return base_image


    def _on_instance_ready(self,first_boot):
        super( CentosBox, self )._on_instance_ready( first_boot )
        if first_boot and self.username( ) == 'root':
            self.__create_admin()
            self._set_username( ADMIN_USER )
            self.__setup_admin()

    @fabric_task
    def __create_admin(self):
        # don't clear screen on logout, it's annoying
        run( r"sed -i -r 's!^(/usr/bin/)?clear!# \0!' /etc/skel/.bash_logout ~/.bash_logout" )
        # Imitate the security model of Canonical's Ubuntu AMIs: Create an admin user that can sudo
        # without password and disable root logins via console and ssh.
        run( 'useradd -m -s /bin/bash {0}'.format( ADMIN_USER ) )
        self._propagate_authorized_keys( ADMIN_USER )
        run( 'rm ~/.ssh/authorized_keys' )
        run( 'echo "{0}  ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers'.format( ADMIN_USER ) )
        run( 'passwd -l root' )
        run( 'echo PermitRootLogin no >> /etc/ssh/sshd_config' )

    @fabric_task
    def __setup_admin(self):
        run( "echo 'export PATH=\"/usr/local/sbin:/usr/sbin:/sbin:$PATH\"' >> ~/.bash_profile" )


