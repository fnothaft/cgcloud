from StringIO import StringIO
import contextlib
import csv
import urllib2
from fabric.operations import sudo, put
from box import fabric_task
from cghub.cloud.core.agent_box import AgentBox
from cghub.cloud.core.cloud_init_box import CloudInitBox
from cghub.cloud.core.package_manager_box import PackageManagerBox
from cghub.cloud.core.rc_local_box import RcLocalBox

BASE_URL = 'http://cloud-images.ubuntu.com'


class TemplateDict( dict ):
    def matches( self, other ):
        return all( v == other.get( k ) for k, v in self.iteritems( ) )


class UbuntuBox( AgentBox, PackageManagerBox, CloudInitBox, RcLocalBox ):
    """
    A box representing EC2 instances that boot from one of Ubuntu's cloud-image AMIs
    """

    def release( self ):
        """
        :return: the code name of the Ubuntu release, e.g. "precise"
        """
        raise NotImplementedError( )

    @staticmethod
    def __find_image( template, url, fields ):
        matches = [ ]
        with contextlib.closing( urllib2.urlopen( url ) ) as stream:
            images = csv.DictReader( stream, fields, delimiter='\t' )
            for image in images:
                if template.matches( image ):
                    matches.append( image )
        if len( matches ) < 1:
            raise RuntimeError( 'No matching images' )
        if len( matches ) > 1:
            raise RuntimeError( 'More than one matching images: %s' % matches )
        match = matches[ 0 ]
        return match

    def username( self ):
        return 'ubuntu'

    def _base_image( self ):
        release = self.release( )
        image_info = self.__find_image(
            template=TemplateDict( release=release,
                                   purpose='server',
                                   release_type='release',
                                   storage_type='ebs',
                                   arch='amd64',
                                   region=self.ctx.region,
                                   hypervisor='paravirtual' ),
            url='%s/query/%s/server/released.current.txt' % ( BASE_URL, release ),
            fields=[
                'release', 'purpose', 'release_type', 'release_date',
                'storage_type', 'arch', 'region', 'ami_id', 'aki_id',
                'dont_know', 'hypervisor' ] )
        image_id = image_info[ 'ami_id' ]
        return self.ctx.ec2.get_image( image_id )

    apt_get = 'DEBIAN_FRONTEND=readline apt-get -q -y'

    @fabric_task
    def _sync_package_repos( self ):
        sudo( '%s update' % self.apt_get )

    @fabric_task
    def _upgrade_installed_packages( self ):
        sudo( '%s upgrade' % self.apt_get )

    @fabric_task
    def _install_packages( self, packages ):
        packages = " ".join( packages )
        sudo( '%s install %s' % (self.apt_get, packages ) )

    @fabric_task
    def _debconf_set_selection( self, *debconf_selections, **sudo_kwargs ):
        for debconf_selection in debconf_selections:
            if '"' in debconf_selection:
                raise RuntimeError( 'Double quotes in debconf selections are not supported yet' )
        sudo( 'debconf-set-selections <<< "%s"' % '\n'.join( debconf_selections ), **sudo_kwargs )

    @fabric_task
    def _register_init_script( self, script, name ):
        put(
            local_path=StringIO( script ),
            remote_path='/etc/init/%s.conf' % name,
            use_sudo=True )

    def _ssh_service_name( self ):
        return 'ssh'

