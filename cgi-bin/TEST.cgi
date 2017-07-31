#!/m1/shared/bin/perl -wT

# CDL Patron Authenticator
# Parameter: barcode (Voyager patron barcode)
# Returns: XML document with info about patron's status and rights for document delivery 
# Used by CDL's Request system
#
# Revisions:
#   2007-01-22 akohler: modified query to fix error when patrons have multiple WDDS categories
#   2007-01-22 akohler: fixed $mday off-by-one error in write_log()
#   2008-07-04 akohler: switched from /usr/bin/perl to /m1/shared/bin/perl, and $ORACLE_HOME to Oracle 10g

use strict;
#$ENV{'ORACLE_HOME'} = '/oracle/app/oracle/product/9.2.0';
$ENV{'ORACLE_HOME'} = '/oracle/app/oracle/product/10.2.0/db_1';
#use lib '/m1/voyager/ucladb/local/cdl/lib';
#use Data::Dumper;
use Sys::Hostname;
use DBI;
use CGI;

# connection settings
my $dbsid = "VGER";
my $config_file = "../config/get_patron_info.cfg";
open DATA, $config_file or die "Can't read config file: $!";
chomp(my $dbuserpass = <DATA>);
close DATA;
my $dbhost = "localhost";

### vars to write to log file darrowco@library.ucla.edu 050307
my $barcoder = 0;

my %patron = ();
my $rows = 0;
my $xml_retval = 0;
my $dbh;

# Doesn't work, even with Sys::Hostname above
# $main::host = hostname;
# 2010-07-11 akohler: not sure what this is used for, other than info in the XML output
$main::host = "ils-db-prod";
$main::transct = 0;

my $cgi = new CGI;
my $barcode = $cgi->param('barcode');

while (1)  {

  open_db_connection();
  unless (defined $dbh) {
    $xml_retval = 2;
    last;
  }

  $barcode =~ s/([A-Z]*\d+)/$1/;
#  $barcoder = $barcode; ###dhc

  # Fill patron structure with data
  ($rows, %patron) = get_patron_info_by_barcode($barcode);
  if ($rows != 1) {
    $xml_retval = 1;
  }

# print "$rows : $patron{'FirstName'}\n";

  close_db_connection();

  last;
}

print $cgi->header(-type => 'text/xml');
print to_xml($xml_retval, %patron);

write_log($barcode, $xml_retval);

exit 0;

##############################
sub open_db_connection {
  my $dsn = "dbi:Oracle:host=$dbhost;sid=$dbsid";
  my ($user_name, $password) = split /\//, $dbuserpass;
  $dbh = DBI->connect ($dsn, $user_name, $password, {RaiseError => 0});
}

##############################
sub close_db_connection {
  $dbh->disconnect();
}

##############################
sub get_patron_info_by_barcode {
  my $barcode = shift;
  my %patron;
  my @data;

  my $sql = 
    "SELECT
       p.patron_id
     , p.last_name AS LastName
     , p.first_name AS FirstName
     , p.middle_name AS MiddleName
     , To_Char(p.expire_date, 'YYYY-MM-DD HH24:MI:SS') AS ExpirationDate
     , To_Char(p.suspension_date, 'YYYY-MM-DD HH24:MI:SS') AS SuspensionDate
     , (p.total_fees_due / 100) AS FeeBalance
     , (SELECT psc.patron_stat_desc FROM patron_stat_code psc INNER JOIN patron_stats ps ON psc.patron_stat_id = ps.patron_stat_id
          WHERE ps.patron_id = p.patron_id AND psc.patron_stat_desc LIKE 'WDDS%'
          AND ROWNUM < 2) AS DeliveryOption -- ROWNUM < 2 guarantees no multiple rows in subquery
     , pb.patron_barcode AS Barcode
     , pg.patron_group_code AS PatronType
     , (SELECT address_line1 FROM patron_address WHERE patron_id = p.patron_id
          AND address_type = 3 AND ROWNUM < 2) AS EmailAddress -- ROWNUM < 2 guarantees no multiple rows in subquery
     , (SELECT COUNT(*) FROM circ_transactions WHERE patron_id = p.patron_id
          AND recall_due_date IS NOT NULL AND recall_due_date < SYSDATE) AS OverdueRecall
     FROM patron p
     INNER JOIN patron_barcode pb ON p.patron_id = pb.patron_id
     INNER JOIN patron_group pg ON pb.patron_group_id = pg.patron_group_id
     WHERE pb.patron_barcode = Upper('$barcode')
     AND pb.barcode_status = 1 -- Active
    ";

  my $sth = $dbh->prepare($sql);
  my $result = $sth->execute() || die $sth->errstr;

  my $rows = 0;

  while (@data = $sth->fetchrow_array()) {
    # Store just the first row in the patron structure, but keep count of rows
    # for later decisionmaking

    $rows = $sth->rows;
    if ($rows == 1) {
      $patron{'PatronID'} = ($data[0] ? $data[0] : '');
      $patron{'LastName'} = ($data[1] ? $data[1] : '');
      $patron{'FirstName'} = ($data[2] ? $data[2] : '');
      $patron{'MiddleName'} = ($data[3] ? $data[3] : '');
      $patron{'ExpirationDate'} = ($data[4] ? $data[4] : '');
      $patron{'SuspensionDate'} = ($data[5] ? $data[5] : '');
      $patron{'FeeBalance'} = $data[6]; # already defaults to 0
      $patron{'DeliveryOption'} = ($data[7] ? $data[7] : '');
      $patron{'Barcode'} = ($data[8] ? $data[8] : '');
      $patron{'PatronType'} = ($data[9] ? $data[9] : '');
      $patron{'EmailAddress'} = ($data[10] ? $data[10] : '');
      $patron{'OverdueRecall'} = ($data[11] == 0 ? 'N' : 'Y');
    }
  }

  return ($rows, %patron);
}

##############################
sub to_xml {
  my $xml_retval = shift;
  my %patron = @_;
  my $now = localtime;
  $now =~ s/ /_/g;
  my $transid = "${main::host}-$now-${main::transct}";

  my $xml = "";
  $xml .= qq(<?xml version="1.0" encoding="ISO-8859-1"?>\n);
  $xml .= "<PatronAuthenticationData>\n";
  $xml .= "\t<Version>2.0</Version>\n";
  $xml .= "\t<Responder>$main::host</Responder>\n";
  $xml .= "\t<TransactionID>$transid</TransactionID>\n";
  $xml .= "\t<ResponseCode>$xml_retval</ResponseCode>\n";

  if ($xml_retval == 0) {
    $xml .= "\t<PatronInfo>\n";
    $xml .= "\t\t<Barcode>$patron{'Barcode'}</Barcode>\n";
    $xml .= "\t\t<FirstName>$patron{'FirstName'}</FirstName>\n" if $patron{'FirstName'} ne "";
    $xml .= "\t\t<MiddleName>$patron{'MiddleName'}</MiddleName>\n" if $patron{'MiddleName'} ne "";
    $xml .= "\t\t<LastName>$patron{'LastName'}</LastName>\n" if $patron{'LastName'} ne "";
    $xml .= "\t\t<PatronType>$patron{'PatronType'}</PatronType>\n" if $patron{'PatronType'} ne "";
    $xml .= "\t\t<DeliveryOption>$patron{'DeliveryOption'}</DeliveryOption>\n" if $patron{'DeliveryOption'} ne "";
    $xml .= "\t\t<ExpirationDate>$patron{'ExpirationDate'}</ExpirationDate>\n" if $patron{'ExpirationDate'} ne "";
    $xml .= "\t\t<SuspensionDate>$patron{'SuspensionDate'}</SuspensionDate>\n" if $patron{'SuspensionDate'} ne "";
    $xml .= "\t\t<EmailAddress>$patron{'EmailAddress'}</EmailAddress>\n" if $patron{'EmailAddress'} ne "";
    $xml .= "\t\t<FeeBalance>$patron{'FeeBalance'}</FeeBalance>\n";
    $xml .= "\t\t<OverdueRecall>$patron{'OverdueRecall'}</OverdueRecall>\n";
    $xml .= "\t</PatronInfo>\n";
  }

  $xml .= "</PatronAuthenticationData>\n";

  return $xml;
}

##############################
sub write_log {
  my $barcode = shift;
  my $xml_retval = shift;

  # log file will be written by the userid "nobody" running httpd
  # although userid "voyager" tends to own everything in /m1
  open( LOGGER, ">>/m1/voyager/ucladb/local/cdl/log/get_patron_info.log" ) || die "could not open log file: /m1/voyager/ucladb/local/cdl/log/get_patron_info.log\n";
  my ($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = localtime(time);
  $year+=1900;
  $mon+=1;
  # 2007-01-22 akohler: mday is 1-based and does not require adjustment
  # $mday+=1;
  print LOGGER "$year/";
  if( $mon <= 9 ){
      print LOGGER "0$mon/";
  } else {
      print LOGGER "$mon/";
  }
  if( $mday <= 9 ){
      print LOGGER "0$mday ";
  } else {
      print LOGGER "$mday ";
  }
  if( $hour <= 9 ){
      print LOGGER "0$hour:";
  } else {
      print LOGGER "$hour:";
  }
  if( $min <= 9 ){
      print LOGGER "0$min:";
  } else {
      print LOGGER "$min:";
  }
  if( $sec <= 9 ){
      print LOGGER "0$sec ";
  } else {
      print LOGGER "$sec ";
  }
  print LOGGER "Barcode $barcode ";
  print LOGGER "XML $xml_retval\n";
  close LOGGER;
}

